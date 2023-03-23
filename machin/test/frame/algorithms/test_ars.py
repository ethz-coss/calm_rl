from machin.machin.model.nets.base import static_module_wrapper as smw
from machin.machin.frame.algorithms.ars import ARS, RunningStat
from machin.machin.frame.helpers.servers import model_server_helper
from machin.machin.utils.helper_classes import Counter
from machin.machin.utils.conf import Config
from machin.machin.utils.learning_rate import gen_learning_rate_func
from machin.machin.env.utils.openai_gym import disable_view_window
from torch.optim.lr_scheduler import LambdaLR
from test.frame.algorithms.utils import unwrap_time_limit, Smooth
from test.util_run_multi import *
from test.util_fixtures import *
from test.util_platforms import linux_only_forall

import os
import torch as t
import torch.nn as nn
import gym


linux_only_forall()


class TestRunningStat:
    @pytest.mark.parametrize("shape", ((), (3,), (3, 4)))
    def test_push(self, shape):
        vals = []
        rs = RunningStat(shape)
        for _ in range(5):
            val = t.randn(shape, dtype=t.float64)
            rs.push(val)
            vals.append(val)
            m = t.mean(t.stack(vals), dim=0)
            assert t.allclose(rs.mean, m)
            v = (
                t.square(m)
                if (len(vals) == 1)
                else t.var(t.stack(vals), dim=0, unbiased=True)
            )
            assert t.allclose(rs.var, v)

    @pytest.mark.parametrize("shape", ((), (3,), (3, 4)))
    def test_update(self, shape):
        rs1 = RunningStat(shape)
        rs2 = RunningStat(shape)
        rs = RunningStat(shape)
        for _ in range(5):
            val = t.randn(shape, dtype=t.float64)
            rs1.push(val)
            rs.push(val)
        for _ in range(9):
            val = t.randn(shape, dtype=t.float64)
            rs2.push(val)
            rs.push(val)
        rs1.update(rs2)
        assert t.allclose(rs.mean, rs1.mean)
        assert t.allclose(rs.std, rs1.std)


# class ActorDiscrete(nn.Module):
#     def __init__(self, state_dim, action_dim):
#         super(ActorDiscrete, self).__init__()
#
#         self.fc1 = nn.Linear(state_dim, 16)
#         self.fc2 = nn.Linear(16, action_dim)
#
#     def forward(self, state):
#         a = self.fc1(state)
#         a = t.argmax(self.fc2(a), dim=1).item()
#         return a


class ActorDiscrete(nn.Module):
    def __init__(self, state_dim, action_dim):
        super().__init__()
        self.fc = nn.Linear(state_dim, action_dim, bias=False)

    def forward(self, state):
        a = t.argmax(self.fc(state), dim=1).item()
        return a


class TestARS:
    # configs and definitions
    # Cartpole-v0 can be solved:
    # within 200 episodes, using single layer Actor
    # within 400 episodes, using double layer Actor

    # However, ARS fails to deal with pendulum v0:
    # Actor((st, 16)->(16, a)), noise_std=0.01, lr=0.05, rollout=9, optim=Adam)
    # reaches mean score = -700 at 10000 episodes
    # Actor((st, a)), noise_std=0.01, lr=0.05, rollout=9, optim=Adam)
    # reaches mean score = -1100 at 15000 episodes
    # and Adam optimizer is better than SGD
    disable_view_window()
    c = Config()
    c.env_name = "CartPole-v0"
    c.env = unwrap_time_limit(gym.make(c.env_name))
    c.observe_dim = 4
    c.action_num = 2
    c.max_episodes = 1000
    c.max_steps = 200
    c.solved_reward = 150
    c.solved_repeat = 5

    @staticmethod
    def ars(device, dtype):
        c = TestARS.c
        actor = smw(
            ActorDiscrete(c.observe_dim, c.action_num).type(dtype).to(device),
            device,
            device,
        )
        servers = model_server_helper(model_num=1)
        world = get_world()
        ars_group = world.create_rpc_group("ars", ["0", "1", "2"])
        ars = ARS(
            actor,
            t.optim.SGD,
            ars_group,
            servers,
            noise_std_dev=0.1,
            learning_rate=0.1,
            noise_size=1000000,
            rollout_num=6,
            used_rollout_num=6,
            normalize_state=True,
        )
        return ars

    @staticmethod
    def ars_lr(device, dtype):
        c = TestARS.c
        actor = smw(
            ActorDiscrete(c.observe_dim, c.action_num).type(dtype).to(device),
            device,
            device,
        )
        lr_func = gen_learning_rate_func(
            [(0, 1e-3), (200000, 3e-4)], logger=default_logger
        )
        servers = model_server_helper(model_num=1)
        world = get_world()
        ars_group = world.create_rpc_group("ars", ["0", "1", "2"])
        ars = ARS(
            actor,
            t.optim.SGD,
            ars_group,
            servers,
            noise_size=1000000,
            lr_scheduler=LambdaLR,
            lr_scheduler_args=((lr_func,),),
        )
        return ars

    ########################################################################
    # Test for ARS acting
    ########################################################################
    @staticmethod
    @run_multi(
        expected_results=[True, True, True],
        pass_through=["device", "dtype"],
        timeout=180,
    )
    @setup_world
    def test_act(_, device, dtype):
        c = TestARS.c
        ars = TestARS.ars(device, dtype)
        state = t.zeros([1, c.observe_dim], dtype=dtype)
        ars.act({"state": state}, "original")
        ars.act({"state": state}, ars.get_actor_types()[0])
        with pytest.raises(ValueError):
            ars.act({"state": state}, "some_invalid_actor_type")
        return True

    ########################################################################
    # Test for ARS storage
    ########################################################################
    @staticmethod
    @run_multi(
        expected_results=[True, True, True],
        pass_through=["device", "dtype"],
        timeout=180,
    )
    @setup_world
    def test_store_reward(_, device, dtype):
        ars = TestARS.ars(device, dtype)
        ars.store_reward(0.0, ars.get_actor_types()[0])
        with pytest.raises(ValueError):
            ars.store_reward(1.0, "some_invalid_actor_type")
        return True

    ########################################################################
    # Test for ARS update
    ########################################################################
    @staticmethod
    @run_multi(
        expected_results=[True, True, True],
        pass_through=["device", "dtype"],
        timeout=180,
    )
    @setup_world
    def test_update(_, device, dtype):
        c = TestARS.c
        ars = TestARS.ars(device, dtype)
        for at in ars.get_actor_types():
            # get action will cause filters to initialize
            _action = ars.act({"state": t.zeros([1, c.observe_dim], dtype=dtype)}, at)
            if at.startswith("neg"):
                ars.store_reward(1.0, at)
            else:
                ars.store_reward(0.0, at)
        ars.update()
        return True

    ########################################################################
    # Test for ARS save & load
    ########################################################################
    # Skipped, it is the same as base

    ########################################################################
    # Test for ARS lr_scheduler
    ########################################################################
    @staticmethod
    @run_multi(
        expected_results=[True, True, True],
        pass_through=["device", "dtype"],
        timeout=180,
    )
    @setup_world
    def test_lr_scheduler(_, device, dtype):
        ars = TestARS.ars_lr(device, dtype)
        ars.update_lr_scheduler()
        return True

    ########################################################################
    # Test for ARS config & init
    ########################################################################
    @staticmethod
    @run_multi(expected_results=[True, True, True], timeout=180)
    @setup_world
    def test_config_init(_):
        c = TestARS.c
        config = ARS.generate_config({})
        config["frame_config"]["models"] = ["ActorDiscrete"]
        config["frame_config"]["model_kwargs"] = [
            {"state_dim": c.observe_dim, "action_dim": c.action_num}
        ]
        ars = ARS.init_from_config(config)

        for at in ars.get_actor_types():
            # get action will cause filters to initialize
            _action = ars.act(
                {"state": t.zeros([1, c.observe_dim], dtype=t.float32)}, at
            )
            if at.startswith("neg"):
                ars.store_reward(1.0, at)
            else:
                ars.store_reward(0.0, at)
        ars.update()
        return True

    ########################################################################
    # Test for ARS full training.
    ########################################################################
    @staticmethod
    @run_multi(expected_results=[True, True, True], timeout=1800)
    @setup_world
    def test_full_train(rank):
        training_group = get_world().create_rpc_group("training", ["0", "1", "2"])

        c = TestARS.c
        ars = TestARS.ars("cpu", t.float32)

        # begin training
        episode, step = Counter(), Counter()
        reward_fulfilled = Counter()
        smoother = Smooth()
        terminal = False
        env = c.env
        env.seed(rank)

        # for cpu usage viewing
        default_logger.info(f"{rank}, pid {os.getpid()}")

        # make sure all things are initialized.
        training_group.barrier()

        while episode < c.max_episodes:
            episode.count()

            all_reward = 0
            for at in ars.get_actor_types():
                total_reward = 0

                # batch size = 1
                state = t.tensor(env.reset(), dtype=t.float32)
                while not terminal and step <= c.max_steps:
                    step.count()
                    with t.no_grad():
                        # agent model inference
                        action = ars.act({"state": state.unsqueeze(0)}, at)
                        state, reward, terminal, __ = env.step(action)
                        state = t.tensor(state, dtype=t.float32)
                        total_reward += float(reward)
                step.reset()
                terminal = False
                ars.store_reward(total_reward, at)
                all_reward += total_reward

            # update
            ars.update()
            smoother.update(all_reward / len(ars.get_actor_types()))
            default_logger.info(
                f"Process {rank} Episode {episode} total reward={smoother.value:.2f}"
            )

            if smoother.value > c.solved_reward:
                reward_fulfilled.count()
                if reward_fulfilled >= c.solved_repeat:
                    default_logger.info("Environment solved!")
                    try:
                        training_group.pair(f"solved", True)
                    except KeyError:
                        # already solved in another process
                        pass
            else:
                reward_fulfilled.reset()

            training_group.barrier()
            if training_group.is_paired("solved"):
                return True

        raise RuntimeError("ARS Training failed.")

from torch.optim.lr_scheduler import LambdaLR
from torch.distributions import Categorical
from machin.machin.model.nets.base import static_module_wrapper as smw
from machin.machin.frame.algorithms.impala import IMPALA
from machin.machin.frame.helpers.servers import model_server_helper
from machin.machin.utils.helper_classes import Counter
from machin.machin.utils.learning_rate import gen_learning_rate_func
from machin.machin.utils.conf import Config
from machin.machin.env.utils.openai_gym import disable_view_window
from test.frame.algorithms.utils import unwrap_time_limit, Smooth
from test.util_run_multi import *
from test.util_fixtures import *
from test.util_platforms import linux_only_forall

import os
import torch as t
import torch.nn as nn
import gym


linux_only_forall()


class Actor(nn.Module):
    def __init__(self, state_dim, action_num):
        super().__init__()

        self.fc1 = nn.Linear(state_dim, 16)
        self.fc2 = nn.Linear(16, 16)
        self.fc3 = nn.Linear(16, action_num)

    def forward(self, state, action=None):
        a = t.relu(self.fc1(state))
        a = t.relu(self.fc2(a))
        probs = t.softmax(self.fc3(a), dim=1)
        dist = Categorical(probs=probs)
        act = action if action is not None else dist.sample()
        act_entropy = dist.entropy()
        act_log_prob = dist.log_prob(act.flatten())
        return act, act_log_prob, act_entropy


class Critic(nn.Module):
    def __init__(self, state_dim):
        super().__init__()

        self.fc1 = nn.Linear(state_dim, 16)
        self.fc2 = nn.Linear(16, 16)
        self.fc3 = nn.Linear(16, 1)

    def forward(self, state):
        v = t.relu(self.fc1(state))
        v = t.relu(self.fc2(v))
        v = self.fc3(v)
        return v


class TestIMPALA:
    # configs and definitions
    disable_view_window()
    c = Config()
    # Note: online policy algorithms such as PPO and A3C does not
    # work well in Pendulum (reason unknown)
    # and MountainCarContinuous (sparse returns)
    c.env_name = "CartPole-v0"
    c.env = unwrap_time_limit(gym.make(c.env_name))
    c.observe_dim = 4
    c.action_num = 2
    c.max_episodes = 20000
    c.max_steps = 200
    c.replay_size = 10000
    c.solved_reward = 150
    c.solved_repeat = 5

    @staticmethod
    def impala(device, dtype, use_lr_sch=False):
        c = TestIMPALA.c
        actor = smw(
            Actor(c.observe_dim, c.action_num).type(dtype).to(device), device, device
        )
        critic = smw(Critic(c.observe_dim).type(dtype).to(device), device, device)
        servers = model_server_helper(model_num=1)
        world = get_world()
        # process 0 and 1 will be workers, and 2 will be trainer
        impala_group = world.create_rpc_group("impala", ["0", "1", "2"])

        if use_lr_sch:
            lr_func = gen_learning_rate_func(
                [(0, 1e-3), (200000, 3e-4)], logger=default_logger
            )
            impala = IMPALA(
                actor,
                critic,
                t.optim.Adam,
                nn.MSELoss(reduction="sum"),
                impala_group,
                servers,
                lr_scheduler=LambdaLR,
                lr_scheduler_args=((lr_func,), (lr_func,)),
            )
        else:
            impala = IMPALA(
                actor,
                critic,
                t.optim.Adam,
                nn.MSELoss(reduction="sum"),
                impala_group,
                servers,
            )
        return impala

    ########################################################################
    # Test for IMPALA acting
    ########################################################################
    @staticmethod
    @run_multi(
        expected_results=[True, True, True],
        pass_through=["device", "dtype"],
        timeout=180,
    )
    @setup_world
    def test_act(_, device, dtype):
        c = TestIMPALA.c
        impala = TestIMPALA.impala(device, dtype)

        state = t.zeros([1, c.observe_dim], dtype=dtype)
        impala.act({"state": state})
        return True

    ########################################################################
    # Test for IMPALA action evaluation
    ########################################################################
    @staticmethod
    @run_multi(
        expected_results=[True, True, True],
        pass_through=["device", "dtype"],
        timeout=180,
    )
    @setup_world
    def test_eval_action(_, device, dtype):
        c = TestIMPALA.c
        impala = TestIMPALA.impala(device, dtype)

        state = t.zeros([1, c.observe_dim], dtype=dtype)
        action = t.zeros([1, 1], dtype=t.int)
        impala._eval_act({"state": state}, {"action": action})
        return True

    ########################################################################
    # Test for IMPALA criticizing
    ########################################################################
    @staticmethod
    @run_multi(
        expected_results=[True, True, True],
        pass_through=["device", "dtype"],
        timeout=180,
    )
    @setup_world
    def test__criticize(_, device, dtype):
        c = TestIMPALA.c
        impala = TestIMPALA.impala(device, dtype)

        state = t.zeros([1, c.observe_dim], dtype=dtype)
        impala._criticize({"state": state})
        return True

    ########################################################################
    # Test for IMPALA storage
    ########################################################################
    @staticmethod
    @run_multi(
        expected_results=[True, True, True],
        pass_through=["device", "dtype"],
        timeout=180,
    )
    @setup_world
    def test_store_episode(_, device, dtype):
        c = TestIMPALA.c
        impala = TestIMPALA.impala(device, dtype)

        old_state = state = t.zeros([1, c.observe_dim], dtype=dtype)
        action = t.zeros([1, 1], dtype=t.int)
        episode = [
            {
                "state": {"state": old_state},
                "action": {"action": action},
                "next_state": {"state": state},
                "reward": 0,
                "action_log_prob": 0.1,
                "terminal": False,
            }
            for _ in range(3)
        ]
        impala.store_episode(episode)
        return True

    ########################################################################
    # Test for IMPALA update
    ########################################################################
    @staticmethod
    @run_multi(
        expected_results=[True, True, True],
        pass_through=["device", "dtype"],
        timeout=180,
    )
    @setup_world
    def test_update(rank, device, dtype):
        c = TestIMPALA.c
        impala = TestIMPALA.impala(device, dtype)

        old_state = state = t.zeros([1, c.observe_dim], dtype=dtype)
        action = t.zeros([1, 1], dtype=t.int)
        if rank == 0:
            # episode length = 3
            impala.store_episode(
                [
                    {
                        "state": {"state": old_state},
                        "action": {"action": action},
                        "next_state": {"state": state},
                        "reward": 0,
                        "action_log_prob": 0.1,
                        "terminal": False,
                    }
                    for _ in range(3)
                ]
            )
        elif rank == 1:
            # episode length = 2
            impala.store_episode(
                [
                    {
                        "state": {"state": old_state},
                        "action": {"action": action},
                        "next_state": {"state": state},
                        "reward": 0,
                        "action_log_prob": 0.1,
                        "terminal": False,
                    }
                    for _ in range(2)
                ]
            )
        if rank == 2:
            sleep(2)
            impala.update(
                update_value=True, update_target=True, concatenate_samples=True
            )
        return True

    ########################################################################
    # Test for IMPALA save & load
    ########################################################################
    # Skipped, it is the same as base framework

    ########################################################################
    # Test for IMPALA lr_scheduler
    ########################################################################
    @staticmethod
    @run_multi(
        expected_results=[True, True, True],
        pass_through=["device", "dtype"],
        timeout=180,
    )
    @setup_world
    def test_lr_scheduler(_, device, dtype):
        impala = TestIMPALA.impala(device, dtype)

        impala.update_lr_scheduler()
        return True

    ########################################################################
    # Test for IMPALA config & init
    ########################################################################
    @staticmethod
    @run_multi(expected_results=[True, True, True], timeout=180)
    @setup_world
    def test_config_init(rank):
        c = TestIMPALA.c
        config = IMPALA.generate_config({})
        config["frame_config"]["models"] = ["Actor", "Critic"]
        config["frame_config"]["model_kwargs"] = [
            {"state_dim": c.observe_dim, "action_num": c.action_num},
            {"state_dim": c.observe_dim},
        ]
        impala = IMPALA.init_from_config(config)

        old_state = state = t.zeros([1, c.observe_dim], dtype=t.float32)
        action = t.zeros([1, 1], dtype=t.int)

        if rank == 0:
            # episode length = 3
            impala.store_episode(
                [
                    {
                        "state": {"state": old_state},
                        "action": {"action": action},
                        "next_state": {"state": state},
                        "reward": 0,
                        "action_log_prob": 0.1,
                        "terminal": False,
                    }
                    for _ in range(3)
                ]
            )
        elif rank == 1:
            # episode length = 2
            impala.store_episode(
                [
                    {
                        "state": {"state": old_state},
                        "action": {"action": action},
                        "next_state": {"state": state},
                        "reward": 0,
                        "action_log_prob": 0.1,
                        "terminal": False,
                    }
                    for _ in range(2)
                ]
            )
        if rank == 2:
            sleep(2)
            impala.update(
                update_value=True, update_target=True, concatenate_samples=True
            )
        return True

    ########################################################################
    # Test for IMPALA full training.
    ########################################################################
    @staticmethod
    @run_multi(expected_results=[True, True, True], timeout=1800)
    @setup_world
    def test_full_train(rank):
        training_group = get_world().create_rpc_group("training", ["0", "1", "2"])

        c = TestIMPALA.c
        impala = TestIMPALA.impala("cpu", t.float32)

        # perform manual syncing to decrease the number of rpc calls
        impala.set_sync(False)

        # begin training
        episode, step = Counter(), Counter()
        reward_fulfilled = Counter()
        smoother = Smooth()
        terminal = False
        env = c.env
        env.seed(rank)

        # make sure all things are initialized.
        training_group.barrier()

        # for cpu usage viewing
        default_logger.info(f"{rank}, pid {os.getpid()}")

        while episode < c.max_episodes:
            episode.count()

            if rank in (0, 1):
                # batch size = 1
                total_reward = 0
                state = t.tensor(env.reset(), dtype=t.float32)

                impala.manual_sync()
                tmp_observations = []
                while not terminal and step <= c.max_steps:
                    step.count()
                    with t.no_grad():
                        old_state = state
                        action, action_log_prob, *_ = impala.act(
                            {"state": old_state.unsqueeze(0)}
                        )
                        state, reward, terminal, _ = env.step(action.item())
                        state = t.tensor(state, dtype=t.float32).flatten()
                        total_reward += float(reward)

                        tmp_observations.append(
                            {
                                "state": {"state": old_state.unsqueeze(0)},
                                "action": {"action": action},
                                "next_state": {"state": state.unsqueeze(0)},
                                "reward": float(reward),
                                "action_log_prob": action_log_prob.item(),
                                "terminal": terminal or step == c.max_steps,
                            }
                        )
                impala.store_episode(tmp_observations)

                smoother.update(total_reward)
                step.reset()
                terminal = False

                default_logger.info(
                    "Process {} Episode {} "
                    "total reward={:.2f}".format(rank, episode, smoother.value)
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
            else:
                # wait for some samples
                if episode.get() > 200:
                    for _ in range(100):
                        impala.update()
                    default_logger.info("Updated 100 times.")

            training_group.barrier()
            if training_group.is_paired("solved"):
                return True

        raise RuntimeError("IMPALA Training failed.")

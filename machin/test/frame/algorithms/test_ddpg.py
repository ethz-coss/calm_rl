from torch.optim.lr_scheduler import LambdaLR
from machin.machin.model.nets.base import static_module_wrapper as smw
from machin.machin.frame.algorithms.ddpg import DDPG
from machin.machin.utils.learning_rate import gen_learning_rate_func
from machin.machin.utils.logging import default_logger as logger
from machin.machin.utils.helper_classes import Counter
from machin.machin.utils.conf import Config
from machin.machin.env.utils.openai_gym import disable_view_window
from test.frame.algorithms.utils import unwrap_time_limit, Smooth
from test.util_fixtures import *
from test.util_platforms import linux_only

import pytest
import torch as t
import torch.nn as nn
import gym


class Actor(nn.Module):
    def __init__(self, state_dim, action_dim, action_range):
        super().__init__()

        self.fc1 = nn.Linear(state_dim, 16)
        self.fc2 = nn.Linear(16, 16)
        self.fc3 = nn.Linear(16, action_dim)
        self.action_range = action_range

    def forward(self, state):
        a = t.relu(self.fc1(state))
        a = t.relu(self.fc2(a))
        a = t.tanh(self.fc3(a)) * self.action_range
        return a


class ActorDiscrete(nn.Module):
    def __init__(self, state_dim, action_dim):
        super().__init__()

        self.fc1 = nn.Linear(state_dim, 16)
        self.fc2 = nn.Linear(16, 16)
        self.fc3 = nn.Linear(16, action_dim)

    def forward(self, state):
        a = t.relu(self.fc1(state))
        a = t.relu(self.fc2(a))
        a = t.softmax(self.fc3(a), dim=1)
        return a


class Critic(nn.Module):
    def __init__(self, state_dim, action_dim):
        super().__init__()

        self.fc1 = nn.Linear(state_dim + action_dim, 16)
        self.fc2 = nn.Linear(16, 16)
        self.fc3 = nn.Linear(16, 1)

    def forward(self, state, action):
        state_action = t.cat([state, action], 1)
        q = t.relu(self.fc1(state_action))
        q = t.relu(self.fc2(q))
        q = self.fc3(q)
        return q


class TestDDPG:
    # configs and definitions
    @pytest.fixture(scope="class")
    def train_config(self):
        disable_view_window()
        c = Config()
        c.env_name = "Pendulum-v0"
        c.env = unwrap_time_limit(gym.make(c.env_name))
        c.observe_dim = 3
        c.action_dim = 1
        c.action_range = 2
        c.max_episodes = 1000
        c.max_steps = 200
        c.noise_param = (0, 0.2)
        c.noise_mode = "normal"
        c.noise_interval = 2
        c.replay_size = 100000
        c.solved_reward = -400
        c.solved_repeat = 5
        return c

    @pytest.fixture(scope="function")
    def ddpg(self, train_config, device, dtype):
        c = train_config
        actor = smw(
            Actor(c.observe_dim, c.action_dim, c.action_range).type(dtype).to(device),
            device,
            device,
        )
        actor_t = smw(
            Actor(c.observe_dim, c.action_dim, c.action_range).type(dtype).to(device),
            device,
            device,
        )
        critic = smw(
            Critic(c.observe_dim, c.action_dim).type(dtype).to(device), device, device
        )
        critic_t = smw(
            Critic(c.observe_dim, c.action_dim).type(dtype).to(device), device, device
        )
        ddpg = DDPG(
            actor,
            actor_t,
            critic,
            critic_t,
            t.optim.Adam,
            nn.MSELoss(reduction="sum"),
            replay_device="cpu",
            replay_size=c.replay_size,
        )
        return ddpg

    @pytest.fixture(scope="function")
    def ddpg_vis(self, train_config, device, dtype, tmpdir):
        # not used for training, only used for testing apis
        c = train_config
        tmp_dir = tmpdir.make_numbered_dir()
        actor = smw(
            Actor(c.observe_dim, c.action_dim, c.action_range).type(dtype).to(device),
            device,
            device,
        )
        actor_t = smw(
            Actor(c.observe_dim, c.action_dim, c.action_range).type(dtype).to(device),
            device,
            device,
        )
        critic = smw(
            Critic(c.observe_dim, c.action_dim).type(dtype).to(device), device, device
        )
        critic_t = smw(
            Critic(c.observe_dim, c.action_dim).type(dtype).to(device), device, device
        )
        ddpg = DDPG(
            actor,
            actor_t,
            critic,
            critic_t,
            t.optim.Adam,
            nn.MSELoss(reduction="sum"),
            replay_device="cpu",
            replay_size=c.replay_size,
            visualize=True,
            visualize_dir=str(tmp_dir),
        )
        return ddpg

    @pytest.fixture(scope="function")
    def ddpg_disc(self, train_config, device, dtype):
        # not used for training, only used for testing apis
        c = train_config
        actor = smw(
            ActorDiscrete(c.observe_dim, c.action_dim).type(dtype).to(device),
            device,
            device,
        )
        actor_t = smw(
            ActorDiscrete(c.observe_dim, c.action_dim).type(dtype).to(device),
            device,
            device,
        )
        critic = smw(
            Critic(c.observe_dim, c.action_dim).type(dtype).to(device), device, device
        )
        critic_t = smw(
            Critic(c.observe_dim, c.action_dim).type(dtype).to(device), device, device
        )
        ddpg = DDPG(
            actor,
            actor_t,
            critic,
            critic_t,
            t.optim.Adam,
            nn.MSELoss(reduction="sum"),
            replay_device="cpu",
            replay_size=c.replay_size,
        )
        return ddpg

    @pytest.fixture(scope="function")
    def ddpg_lr(self, train_config, device, dtype):
        # not used for training, only used for testing apis
        c = train_config
        actor = smw(
            ActorDiscrete(c.observe_dim, c.action_dim).type(dtype).to(device),
            device,
            device,
        )
        actor_t = smw(
            ActorDiscrete(c.observe_dim, c.action_dim).type(dtype).to(device),
            device,
            device,
        )
        critic = smw(
            Critic(c.observe_dim, c.action_dim).type(dtype).to(device), device, device
        )
        critic_t = smw(
            Critic(c.observe_dim, c.action_dim).type(dtype).to(device), device, device
        )
        lr_func = gen_learning_rate_func([(0, 1e-3), (200000, 3e-4)], logger=logger)
        with pytest.raises(TypeError, match="missing .+ positional argument"):
            _ = DDPG(
                actor,
                actor_t,
                critic,
                critic_t,
                t.optim.Adam,
                nn.MSELoss(reduction="sum"),
                replay_device="cpu",
                replay_size=c.replay_size,
                lr_scheduler=LambdaLR,
            )
        ddpg = DDPG(
            actor,
            actor_t,
            critic,
            critic_t,
            t.optim.Adam,
            nn.MSELoss(reduction="sum"),
            replay_device="cpu",
            replay_size=c.replay_size,
            lr_scheduler=LambdaLR,
            lr_scheduler_args=((lr_func,), (lr_func,)),
        )
        return ddpg

    @pytest.fixture(scope="function")
    def ddpg_train(self, train_config):
        c = train_config
        # cpu is faster for testing full training.
        actor = smw(Actor(c.observe_dim, c.action_dim, c.action_range), "cpu", "cpu")
        actor_t = smw(Actor(c.observe_dim, c.action_dim, c.action_range), "cpu", "cpu")
        critic = smw(Critic(c.observe_dim, c.action_dim), "cpu", "cpu")
        critic_t = smw(Critic(c.observe_dim, c.action_dim), "cpu", "cpu")
        ddpg = DDPG(
            actor,
            actor_t,
            critic,
            critic_t,
            t.optim.Adam,
            nn.MSELoss(reduction="sum"),
            replay_device="cpu",
            replay_size=c.replay_size,
        )
        return ddpg

    ########################################################################
    # Test for DDPG contiguous domain acting
    ########################################################################
    def test_contiguous_act(self, train_config, ddpg, dtype):
        c = train_config
        state = t.zeros([1, c.observe_dim], dtype=dtype)
        ddpg.act({"state": state})
        ddpg.act({"state": state}, use_target=True)
        ddpg.act_with_noise({"state": state}, noise_param=(0, 1.0), mode="uniform")
        ddpg.act_with_noise({"state": state}, noise_param=(0, 1.0), mode="normal")
        ddpg.act_with_noise(
            {"state": state}, noise_param=(0, 1.0, -1.0, 1.0), mode="clipped_normal"
        )
        ddpg.act_with_noise(
            {"state": state}, noise_param={"mu": 0, "sigma": 1}, mode="ou"
        )
        with pytest.raises(ValueError, match="Unknown noise type"):
            ddpg.act_with_noise(
                {"state": state}, noise_param=None, mode="some_unknown_noise"
            )

    ########################################################################
    # Test for DDPG discrete domain acting
    ########################################################################
    def test_discrete_act(self, train_config, ddpg_disc, dtype):
        c = train_config
        state = t.zeros([1, c.observe_dim], dtype=dtype)
        ddpg_disc.act_discrete({"state": state})
        ddpg_disc.act_discrete({"state": state}, use_target=True)
        ddpg_disc.act_discrete_with_noise({"state": state})
        ddpg_disc.act_discrete_with_noise({"state": state}, use_target=True)

    ########################################################################
    # Test for DDPG criticizing
    ########################################################################
    def test__criticize(self, train_config, ddpg, dtype):
        c = train_config
        state = t.zeros([1, c.observe_dim], dtype=dtype)
        action = t.zeros([1, c.action_dim], dtype=dtype)
        ddpg._criticize({"state": state}, {"action": action})
        ddpg._criticize({"state": state}, {"action": action}, use_target=True)

    ########################################################################
    # Test for DDPG storage
    ########################################################################
    def test_store_episode(self, train_config, ddpg, dtype):
        c = train_config
        old_state = state = t.zeros([1, c.observe_dim], dtype=dtype)
        action = t.zeros([1, c.action_dim], dtype=dtype)
        ddpg.store_episode(
            [
                {
                    "state": {"state": old_state},
                    "action": {"action": action},
                    "next_state": {"state": state},
                    "reward": 0,
                    "terminal": False,
                }
            ]
        )

    ########################################################################
    # Test for DDPG update
    ########################################################################
    def test_update(self, train_config, ddpg_vis, dtype):
        c = train_config
        old_state = state = t.zeros([1, c.observe_dim], dtype=dtype)
        action = t.zeros([1, c.action_dim], dtype=dtype)
        ddpg_vis.store_episode(
            [
                {
                    "state": {"state": old_state},
                    "action": {"action": action},
                    "next_state": {"state": state},
                    "reward": 0,
                    "terminal": False,
                }
                for _ in range(3)
            ]
        )
        ddpg_vis.update(
            update_value=True,
            update_policy=True,
            update_target=True,
            concatenate_samples=True,
        )
        ddpg_vis.update(
            update_value=False,
            update_policy=False,
            update_target=False,
            concatenate_samples=True,
        )

    ########################################################################
    # Test for DDPG save & load
    ########################################################################
    def test_save_load(self, train_config, ddpg, tmpdir):
        save_dir = tmpdir.make_numbered_dir()
        ddpg.save(
            model_dir=str(save_dir),
            network_map={"critic_target": "critic_t", "actor_target": "actor_t"},
            version=1000,
        )
        ddpg.load(
            model_dir=str(save_dir),
            network_map={"critic_target": "critic_t", "actor_target": "actor_t"},
            version=1000,
        )

    ########################################################################
    # Test for DDPG lr_scheduler
    ########################################################################
    def test_lr_scheduler(self, train_config, ddpg_lr):
        ddpg_lr.update_lr_scheduler()

    ########################################################################
    # Test for DDPG config & init
    ########################################################################
    def test_config_init(self, train_config):
        c = train_config
        config = DDPG.generate_config({})
        config["frame_config"]["models"] = ["Actor", "Actor", "Critic", "Critic"]
        config["frame_config"]["model_kwargs"] = [
            {
                "state_dim": c.observe_dim,
                "action_dim": c.action_dim,
                "action_range": c.action_range,
            }
        ] * 2 + [{"state_dim": c.observe_dim, "action_dim": c.action_dim}] * 2
        ddpg = DDPG.init_from_config(config)

        old_state = state = t.zeros([1, c.observe_dim], dtype=t.float32)
        action = t.zeros([1, c.action_dim], dtype=t.float32)
        ddpg.store_episode(
            [
                {
                    "state": {"state": old_state},
                    "action": {"action": action},
                    "next_state": {"state": state},
                    "reward": 0,
                    "terminal": False,
                }
                for _ in range(3)
            ]
        )
        ddpg.update()

    ########################################################################
    # Test for DDPG full training.
    ########################################################################
    @linux_only
    def test_full_train(self, train_config, ddpg_train):
        c = train_config

        # begin training
        episode, step = Counter(), Counter()
        reward_fulfilled = Counter()
        smoother = Smooth()
        terminal = False

        env = c.env
        env.seed(0)
        while episode < c.max_episodes:
            episode.count()

            # batch size = 1
            total_reward = 0
            state = t.tensor(env.reset(), dtype=t.float32)
            tmp_observations = []
            while not terminal and step <= c.max_steps:
                step.count()
                with t.no_grad():
                    old_state = state

                    # agent model inference
                    if episode.get() % c.noise_interval == 0:
                        action = ddpg_train.act_with_noise(
                            {"state": old_state.unsqueeze(0)},
                            noise_param=c.noise_param,
                            mode=c.noise_mode,
                        )
                    else:
                        action = ddpg_train.act(
                            {"state": old_state.unsqueeze(0)}
                        ).clamp(-c.action_range, c.action_range)

                    state, reward, terminal, _ = env.step(action.cpu().numpy())
                    state = t.tensor(state, dtype=t.float32).flatten()
                    total_reward += float(reward)

                    tmp_observations.append(
                        {
                            "state": {"state": old_state.unsqueeze(0)},
                            "action": {"action": action},
                            "next_state": {"state": state.unsqueeze(0)},
                            "reward": float(reward),
                            "terminal": terminal or step == c.max_steps,
                        }
                    )
            ddpg_train.store_episode(tmp_observations)
            # update
            if episode > 100:
                for i in range(step.get()):
                    ddpg_train.update()

            smoother.update(total_reward)
            step.reset()
            terminal = False

            if episode.get() % c.noise_interval != 0:
                # only log result without noise
                logger.info(f"Episode {episode} total reward={smoother.value:.2f}")

            if smoother.value > c.solved_reward:
                reward_fulfilled.count()
                if reward_fulfilled >= c.solved_repeat:
                    logger.info("Environment solved!")
                    return
            else:
                reward_fulfilled.reset()

        pytest.fail("DDPG Training failed.")

from machin.machin.model.nets.base import static_module_wrapper as smw
from machin.machin.frame.algorithms.maddpg import MADDPG
from machin.machin.utils.learning_rate import gen_learning_rate_func
from machin.machin.utils.logging import default_logger as logger
from machin.machin.utils.helper_classes import Counter
from machin.machin.utils.conf import Config
from machin.machin.env.utils.openai_gym import disable_view_window
from torch.optim.lr_scheduler import LambdaLR
from copy import deepcopy
from test.frame.algorithms.utils import Smooth
from test.util_create_ma_env import create_env
from test.util_fixtures import *
from test.util_platforms import linux_only

import pytest
import torch as t
import torch.nn as nn


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
        # This critic implementation is shared by the prey(DDPG) and
        # predators(MADDPG)
        # Note: For MADDPG
        #       state_dim is the dimension of all states from all agents.
        #       action_dim is the dimension of all actions from all agents.
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


class TestMADDPG:
    # configs and definitions
    @pytest.fixture(scope="class")
    def train_config(self):
        disable_view_window()
        c = Config()
        # the cooperative environment environment provided in
        # https://github.com/openai/multiagent-particle-envs
        c.env_name = "simple_spread"
        c.env = create_env(c.env_name)
        c.env.discrete_action_input = True
        c.agent_num = 3
        c.action_num = c.env.action_space[0].n
        c.observe_dim = c.env.observation_space[0].shape[0]
        # for contiguous tests
        c.test_action_dim = 5
        c.test_action_range = 1
        c.test_observe_dim = 5
        c.test_agent_num = 3
        c.max_episodes = 1000
        c.max_steps = 200
        c.replay_size = 100000
        # from https://github.com/wsjeon/maddpg-rllib/tree/master/plots
        # PROBLEM: I have no idea how they calculate the rewards
        # I cannot replicate their reward curve
        c.solved_reward = -15
        c.solved_repeat = 5
        return c

    @pytest.fixture(scope="function")
    def maddpg(self, train_config, device, dtype):
        c = train_config
        # for simplicity, prey will be trained with predators,
        # Predator can get the observation of prey, same for prey.
        actor = smw(
            ActorDiscrete(c.observe_dim, c.action_num).type(dtype).to(device),
            device,
            device,
        )
        critic = smw(
            Critic(c.observe_dim * c.agent_num, c.action_num * c.agent_num)
            .type(dtype)
            .to(device),
            device,
            device,
        )
        # set visible indexes to [[0], [1], [2]] is equivalent to using DDPG
        maddpg = MADDPG(
            [deepcopy(actor) for _ in range(c.test_agent_num)],
            [deepcopy(actor) for _ in range(c.test_agent_num)],
            [deepcopy(critic) for _ in range(c.test_agent_num)],
            [deepcopy(critic) for _ in range(c.test_agent_num)],
            t.optim.Adam,
            nn.MSELoss(reduction="sum"),
            replay_device="cpu",
            replay_size=c.replay_size,
            pool_type="thread",
        )
        return maddpg

    @pytest.fixture(scope="function")
    def maddpg_disc(self, train_config, device, dtype):
        c = train_config
        actor = smw(
            ActorDiscrete(c.test_observe_dim, c.test_action_dim).type(dtype).to(device),
            device,
            device,
        )
        critic = smw(
            Critic(
                c.test_observe_dim * c.test_agent_num,
                c.test_action_dim * c.test_agent_num,
            )
            .type(dtype)
            .to(device),
            device,
            device,
        )

        maddpg = MADDPG(
            [deepcopy(actor) for _ in range(c.test_agent_num)],
            [deepcopy(actor) for _ in range(c.test_agent_num)],
            [deepcopy(critic) for _ in range(c.test_agent_num)],
            [deepcopy(critic) for _ in range(c.test_agent_num)],
            t.optim.Adam,
            nn.MSELoss(reduction="sum"),
            replay_device="cpu",
            replay_size=c.replay_size,
        )
        return maddpg

    @pytest.fixture(scope="function")
    def maddpg_cont(self, train_config, device, dtype):
        c = train_config
        actor = smw(
            Actor(c.test_observe_dim, c.test_action_dim, c.test_action_range)
            .type(dtype)
            .to(device),
            device,
            device,
        )
        critic = smw(
            Critic(
                c.test_observe_dim * c.test_agent_num,
                c.test_action_dim * c.test_agent_num,
            )
            .type(dtype)
            .to(device),
            device,
            device,
        )

        maddpg = MADDPG(
            [deepcopy(actor) for _ in range(c.test_agent_num)],
            [deepcopy(actor) for _ in range(c.test_agent_num)],
            [deepcopy(critic) for _ in range(c.test_agent_num)],
            [deepcopy(critic) for _ in range(c.test_agent_num)],
            t.optim.Adam,
            nn.MSELoss(reduction="sum"),
            replay_device="cpu",
            replay_size=c.replay_size,
        )
        return maddpg

    @pytest.fixture(scope="function")
    def maddpg_vis(self, train_config, device, dtype, tmpdir):
        c = train_config
        tmp_dir = tmpdir.make_numbered_dir()
        actor = smw(
            Actor(c.test_observe_dim, c.test_action_dim, c.test_action_range)
            .type(dtype)
            .to(device),
            device,
            device,
        )
        critic = smw(
            Critic(
                c.test_observe_dim * c.test_agent_num,
                c.test_action_dim * c.test_agent_num,
            )
            .type(dtype)
            .to(device),
            device,
            device,
        )

        maddpg = MADDPG(
            [deepcopy(actor) for _ in range(c.test_agent_num)],
            [deepcopy(actor) for _ in range(c.test_agent_num)],
            [deepcopy(critic) for _ in range(c.test_agent_num)],
            [deepcopy(critic) for _ in range(c.test_agent_num)],
            t.optim.Adam,
            nn.MSELoss(reduction="sum"),
            replay_device="cpu",
            replay_size=c.replay_size,
            visualize=True,
            visualize_dir=str(tmp_dir),
        )
        return maddpg

    @pytest.fixture(scope="function")
    def maddpg_lr(self, train_config, device, dtype):
        c = train_config
        actor = smw(
            Actor(c.test_observe_dim, c.test_action_dim, c.test_action_range)
            .type(dtype)
            .to(device),
            device,
            device,
        )
        critic = smw(
            Critic(
                c.test_observe_dim * c.test_agent_num,
                c.test_action_dim * c.test_agent_num,
            )
            .type(dtype)
            .to(device),
            device,
            device,
        )
        lr_func = gen_learning_rate_func([(0, 1e-3), (200000, 3e-4)], logger=logger)
        with pytest.raises(TypeError, match="missing .+ positional argument"):
            _ = MADDPG(
                [deepcopy(actor) for _ in range(c.test_agent_num)],
                [deepcopy(actor) for _ in range(c.test_agent_num)],
                [deepcopy(critic) for _ in range(c.test_agent_num)],
                [deepcopy(critic) for _ in range(c.test_agent_num)],
                t.optim.Adam,
                nn.MSELoss(reduction="sum"),
                replay_device="cpu",
                replay_size=c.replay_size,
                lr_scheduler=LambdaLR,
            )
        maddpg = MADDPG(
            [deepcopy(actor) for _ in range(c.test_agent_num)],
            [deepcopy(actor) for _ in range(c.test_agent_num)],
            [deepcopy(critic) for _ in range(c.test_agent_num)],
            [deepcopy(critic) for _ in range(c.test_agent_num)],
            t.optim.Adam,
            nn.MSELoss(reduction="sum"),
            replay_device="cpu",
            replay_size=c.replay_size,
            lr_scheduler=LambdaLR,
            lr_scheduler_args=(
                [(lr_func,)] * c.test_agent_num,
                [(lr_func,)] * c.test_agent_num,
            ),
        )
        return maddpg

    @pytest.fixture(scope="function")
    def maddpg_train(self, train_config):
        c = train_config
        # for simplicity, prey will be trained with predators,
        # Predator can get the observation of prey, same for prey.
        actor = smw(ActorDiscrete(c.observe_dim, c.action_num), "cpu", "cpu")
        critic = smw(
            Critic(c.observe_dim * c.agent_num, c.action_num * c.agent_num),
            "cpu",
            "cpu",
        )
        # set visible indexes to [[0], [1], [2]] is equivalent to using DDPG
        maddpg = MADDPG(
            [deepcopy(actor) for _ in range(c.test_agent_num)],
            [deepcopy(actor) for _ in range(c.test_agent_num)],
            [deepcopy(critic) for _ in range(c.test_agent_num)],
            [deepcopy(critic) for _ in range(c.test_agent_num)],
            t.optim.Adam,
            nn.MSELoss(reduction="sum"),
            replay_device="cpu",
            replay_size=c.replay_size,
            pool_type="thread",
        )
        return maddpg

    ########################################################################
    # Test for MADDPG contiguous domain acting
    ########################################################################
    def test_contiguous_act(self, train_config, maddpg_cont, dtype):
        c = train_config
        states = [
            {"state": t.zeros([1, c.test_observe_dim], dtype=dtype)}
        ] * c.test_agent_num
        maddpg_cont.act(states)
        maddpg_cont.act(states, use_target=True)
        maddpg_cont.act_with_noise(states, noise_param=(0, 1.0), mode="uniform")
        maddpg_cont.act_with_noise(states, noise_param=(0, 1.0), mode="normal")
        maddpg_cont.act_with_noise(
            states, noise_param=(0, 1.0, -1.0, 1.0), mode="clipped_normal"
        )
        maddpg_cont.act_with_noise(states, noise_param={"mu": 0, "sigma": 1}, mode="ou")
        with pytest.raises(ValueError, match="Unknown noise type"):
            maddpg_cont.act_with_noise(
                states, noise_param=None, mode="some_unknown_noise"
            )

    ########################################################################
    # Test for MADDPG discrete domain acting
    ########################################################################
    def test_discrete_act(self, train_config, maddpg_disc, dtype):
        c = train_config
        states = [
            {"state": t.zeros([1, c.test_observe_dim], dtype=dtype)}
        ] * c.test_agent_num
        maddpg_disc.act_discrete(states)
        maddpg_disc.act_discrete(states, use_target=True)
        maddpg_disc.act_discrete_with_noise(states)
        maddpg_disc.act_discrete_with_noise(states, use_target=True)

    ########################################################################
    # Test for MADDPG criticizing
    ########################################################################
    def test__criticize(self, train_config, maddpg_cont, dtype):
        c = train_config
        states = [
            {"state": t.zeros([1, c.test_observe_dim], dtype=dtype)}
        ] * c.test_agent_num
        actions = [
            {"action": t.zeros([1, c.test_action_dim], dtype=dtype)}
        ] * c.test_agent_num
        maddpg_cont._criticize(states, actions, 0)
        maddpg_cont._criticize(states, actions, 1, use_target=True)

    ########################################################################
    # Test for MADDPG storage
    ########################################################################
    def test_store_episodes(self, train_config, maddpg_cont, dtype):
        c = train_config
        old_state = state = t.zeros([1, c.test_observe_dim], dtype=dtype)
        action = t.zeros([1, c.test_action_dim], dtype=dtype)
        maddpg_cont.store_episodes(
            [
                [
                    {
                        "state": {"state": old_state},
                        "action": {"action": action},
                        "next_state": {"state": state},
                        "reward": 0,
                        "terminal": False,
                    }
                ]
            ]
            * c.test_agent_num
        )

    ########################################################################
    # Test for MADDPG update
    ########################################################################
    def test_update(self, train_config, maddpg_cont, dtype):
        c = train_config
        old_state = state = t.zeros([1, c.test_observe_dim], dtype=dtype)
        action = t.zeros([1, c.test_action_dim], dtype=dtype)
        maddpg_cont.store_episodes(
            [
                [
                    {
                        "state": {"state": old_state},
                        "action": {"action": action},
                        "next_state": {"state": state},
                        "reward": 0,
                        "terminal": False,
                    }
                ]
            ]
            * c.test_agent_num
        )
        maddpg_cont.update(
            update_value=True,
            update_policy=True,
            update_target=True,
            concatenate_samples=True,
        )

    def test_vis_update(self, train_config, maddpg_vis, dtype):
        c = train_config
        old_state = state = t.zeros([1, c.test_observe_dim], dtype=dtype)
        action = t.zeros([1, c.test_action_dim], dtype=dtype)
        maddpg_vis.store_episodes(
            [
                [
                    {
                        "state": {"state": old_state},
                        "action": {"action": action},
                        "next_state": {"state": state},
                        "reward": 0,
                        "terminal": False,
                    }
                ]
            ]
            * c.test_agent_num
        )
        maddpg_vis.update(
            update_value=True,
            update_policy=True,
            update_target=True,
            concatenate_samples=True,
        )

    ########################################################################
    # Test for MADDPG save & load
    ########################################################################
    def test_save_load(self, train_config, maddpg_cont, tmpdir):
        save_dir = tmpdir.make_numbered_dir()
        maddpg_cont.save(
            model_dir=str(save_dir),
            network_map={"critic_target": "critic_t", "actor_target": "actor_t"},
            version=1000,
        )
        maddpg_cont.load(
            model_dir=str(save_dir),
            network_map={"critic_target": "critic_t", "actor_target": "actor_t"},
            version=1000,
        )

    ########################################################################
    # Test for MADDPG lr_scheduler
    ########################################################################
    def test_lr_scheduler(self, train_config, maddpg_lr):
        maddpg_lr.update_lr_scheduler()

    ########################################################################
    # Test for MADDPG config & init
    ########################################################################
    def test_config_init(self, train_config):
        c = train_config
        config = MADDPG.generate_config({})
        config["frame_config"]["models"] = [
            ["Actor"] * c.test_agent_num,
            ["Actor"] * c.test_agent_num,
            ["Critic"] * c.test_agent_num,
            ["Critic"] * c.test_agent_num,
        ]
        config["frame_config"]["model_args"] = [[()] * c.test_agent_num] * 4
        config["frame_config"]["model_kwargs"] = (
            [
                [
                    {
                        "state_dim": c.test_observe_dim,
                        "action_dim": c.test_action_dim,
                        "action_range": c.test_action_range,
                    }
                ]
                * c.test_agent_num
            ]
            * 2
            + [
                [
                    {
                        "state_dim": c.test_observe_dim * c.test_agent_num,
                        "action_dim": c.test_action_dim * c.test_agent_num,
                    }
                ]
                * c.test_agent_num
            ]
            * 2
        )

        maddpg = MADDPG.init_from_config(config)

        old_state = state = t.zeros([1, c.test_observe_dim], dtype=t.float32)
        action = t.zeros([1, c.test_action_dim], dtype=t.float32)
        maddpg.store_episodes(
            [
                [
                    {
                        "state": {"state": old_state},
                        "action": {"action": action},
                        "next_state": {"state": state},
                        "reward": 0,
                        "terminal": False,
                    }
                ]
            ]
            * c.test_agent_num
        )
        maddpg.update()

    ########################################################################
    # Test for MADDPG full training.
    ########################################################################
    @linux_only
    def test_full_train(self, train_config, maddpg_train):
        c = train_config

        # begin training
        episode, step = Counter(), Counter()

        # first for prey, second for pred
        smoother = Smooth()
        reward_fulfilled = Counter()
        terminal = False

        env = c.env
        env.seed(0)
        while episode < c.max_episodes:
            episode.count()

            # batch size = 1
            total_reward = 0
            states = [
                t.tensor(st, dtype=t.float32).view(1, c.observe_dim)
                for st in env.reset()
            ]
            tmp_observations_list = [[] for _ in range(c.agent_num)]

            while not terminal and step <= c.max_steps:
                step.count()
                with t.no_grad():
                    old_states = states

                    # agent model inference
                    results = maddpg_train.act_discrete_with_noise(
                        [{"state": st.view(1, c.observe_dim)} for st in states]
                    )
                    actions = [int(r[0]) for r in results]
                    action_probs = [r[1] for r in results]

                    states, rewards, terminals, _ = env.step(actions)
                    states = [
                        t.tensor(st, dtype=t.float32).view(1, c.observe_dim)
                        for st in states
                    ]

                    total_reward += float(sum(rewards)) / c.agent_num

                    for tmp_observations, ost, act, st, rew, term in zip(
                        tmp_observations_list,
                        old_states,
                        action_probs,
                        states,
                        rewards,
                        terminals,
                    ):
                        tmp_observations.append(
                            {
                                "state": {"state": ost},
                                "action": {"action": act},
                                "next_state": {"state": st},
                                "reward": float(rew),
                                "terminal": term or step == c.max_steps,
                            }
                        )

            maddpg_train.store_episodes(tmp_observations_list)
            # update
            if episode > 5:
                for i in range(step.get()):
                    maddpg_train.update()

            # total reward is divided by steps here, since:
            # "Agents are rewarded based on minimum agent distance
            #  to each landmark, penalized for collisions"
            smoother.update(total_reward / step.get())
            logger.info(f"Episode {episode} total steps={step}")
            step.reset()
            terminal = False

            logger.info(f"Episode {episode} total reward={smoother.value:.2f}")

            if smoother.value > c.solved_reward and episode > 20:
                reward_fulfilled.count()
                if reward_fulfilled >= c.solved_repeat:
                    logger.info("Environment solved!")
                    return
            else:
                reward_fulfilled.reset()

        pytest.fail("MADDPG Training failed.")

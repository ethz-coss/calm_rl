from machin.machin.frame.noise.generator import NormalNoiseGen
from machin.machin.frame.noise.param_space_noise import AdaptiveParamNoise, perturb_model
from machin.machin.utils.helper_classes import Switch

import torch as t
import torch.nn as nn


############################################################################
# Test for AdaptiveParamNoise
############################################################################
class TestAdaptiveParamNoise:
    def test_adapt(self):
        spec = AdaptiveParamNoise()
        spec.adapt(1.0)
        spec.adapt(0.0)

    def test_get_dev(self):
        spec = AdaptiveParamNoise()
        spec.get_dev()

    def test_repr(self):
        spec = AdaptiveParamNoise()
        str(spec)


############################################################################
# Test for perturb_model
############################################################################
def _t_eq_eps(tensor_a, tensor_b, epsilon=1e-10):
    if (
        not t.is_tensor(tensor_a)
        or not t.is_tensor(tensor_b)
        or tensor_a.shape != tensor_b.shape
    ):
        return False
    return t.all(t.abs(tensor_a - tensor_b.to(tensor_a.device)) < epsilon)


def test_perturb_model():
    with t.no_grad():
        seed = 0
        model = nn.Linear(2, 2, bias=False)
        optim = t.optim.Adam(model.parameters(), 1e-3)
        model.weight.fill_(1)
        weight_no_noise = t.ones([2, 2])
        weight_stepped = t.tensor(
            [[1.1530995369, 0.9696571231], [0.7811210752, 1.0558431149]]
        )
        model_input = t.ones([1, 2])
        output_no_noise = t.full([1, 2], 2.0)
        output_with_noise = t.tensor([[2.1247568130, 1.8389642239]])
        output_with_noise2 = t.tensor([[1.8739618063, 1.9643428326]])

    p_switch = Switch()
    r_switch = Switch()
    t.manual_seed(seed)

    cancel = perturb_model(model, p_switch, r_switch, debug_backward=True)

    p_switch.on()
    r_switch.on()
    # p-on, r-on
    assert _t_eq_eps(output_with_noise, model(model_input))
    p_switch.off()
    # p-off, r-on
    # will adjust noise parameters
    assert _t_eq_eps(output_no_noise, model(model_input))
    assert _t_eq_eps(model.weight, weight_no_noise)
    p_switch.on()
    r_switch.off()
    # p-on, r-off
    assert _t_eq_eps(output_with_noise, model(model_input))
    r_switch.on()
    # p-on, r-on
    action = model(model_input)
    assert _t_eq_eps(output_with_noise2, action)

    print(model.weight)
    loss = (action - t.ones_like(action)).sum()
    loss.backward()
    print(model.weight)
    optim.step()
    assert _t_eq_eps(model.weight, weight_stepped)

    cancel()


############################################################################
# Test for perturb_model, where a custom noise generation function is used
############################################################################
def test_perturb_model2():
    with t.no_grad():
        seed = 0
        model = nn.Linear(2, 2, bias=False)
        optim = t.optim.Adam(model.parameters(), 1e-3)
        model.weight.fill_(1)
        weight_no_noise = t.ones([2, 2])
        weight_stepped = t.tensor(
            [[1.1530995369, 0.9696571231], [0.7811210752, 1.0558431149]]
        )
        model_input = t.ones([1, 2])
        output_no_noise = t.full([1, 2], 2.0)
        output_with_noise = t.tensor([[2.1247568130, 1.8389642239]])
        output_with_noise2 = t.tensor([[1.8739618063, 1.9643428326]])

    p_switch = Switch()
    r_switch = Switch()
    t.manual_seed(seed)

    def gen_func(shape, device, std_dev):
        gen = NormalNoiseGen(shape)
        return gen(device) * std_dev

    cancel = perturb_model(
        model, p_switch, r_switch, noise_generate_function=gen_func, debug_backward=True
    )

    p_switch.on()
    r_switch.on()
    # p-on, r-on
    assert _t_eq_eps(output_with_noise, model(model_input))
    p_switch.off()
    # p-off, r-on
    # will adjust noise parameters
    assert _t_eq_eps(output_no_noise, model(model_input))
    assert _t_eq_eps(model.weight, weight_no_noise)
    p_switch.on()
    r_switch.off()
    # p-on, r-off
    assert _t_eq_eps(output_with_noise, model(model_input))
    r_switch.on()
    # p-on, r-on
    action = model(model_input)
    assert _t_eq_eps(output_with_noise2, action)

    loss = (action - t.ones_like(action)).sum()
    loss.backward()
    optim.step()
    assert _t_eq_eps(model.weight, weight_stepped)

    cancel()

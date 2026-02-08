from __future__ import annotations

import importlib
import inspect
from typing import Any, Dict, Callable

from .base import Block


def _import_from_entrypoint(entrypoint: str) -> Callable[..., Block]:
    """
    entrypoint format: "module.submodule:SymbolName"
    Example: "app.runtime.blocks.mujoco_sim_real:MuJoCoSimReal"
    """
    if ":" not in entrypoint:
        raise ValueError(
            f"Invalid entrypoint '{entrypoint}'. Expected 'module.submodule:SymbolName'"
        )

    module_name, symbol_name = entrypoint.split(":", 1)
    mod = importlib.import_module(module_name)
    sym = getattr(mod, symbol_name, None)
    if sym is None:
        raise ImportError(f"Entrypoint symbol '{symbol_name}' not found in {module_name}")
    return sym


def _callable_signature(obj: Any) -> inspect.Signature:
    """
    For classes, inspect __init__ (and drop 'self').
    For functions/callables, inspect the object directly.
    """
    if inspect.isclass(obj):
        sig = inspect.signature(obj.__init__)
        params = list(sig.parameters.values())
        # Drop 'self' if present
        if params and params[0].name == "self":
            params = params[1:]
        return sig.replace(parameters=params)
    return inspect.signature(obj)


def _filter_kwargs_for_callable(callable_obj: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    sig = _callable_signature(callable_obj)
    params = sig.parameters

    # If constructor has **kwargs, allow everything
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return kwargs

    allowed = set(params.keys())
    return {k: v for k, v in kwargs.items() if k in allowed}


def create_block(
    block_id: str,
    params: Dict[str, Any],
    entrypoint: str,
    inputs: Dict[str, str],
    outputs: Dict[str, str],
) -> Block:
    """
    Instantiate a block from entrypoint.
    Blocks should accept:
      block_id: str
      params: dict
      inputs: dict(port_name -> topic)
      outputs: dict(port_name -> topic)
    """
    ctor = _import_from_entrypoint(entrypoint)

    full_kwargs = {
        "block_id": block_id,
        "params": params,
        "inputs": inputs,
        "outputs": outputs,
    }

    filtered_kwargs = _filter_kwargs_for_callable(ctor, full_kwargs)

    try:
        return ctor(**filtered_kwargs)
    except TypeError as e:
        raise TypeError(
            f"Failed to instantiate block '{block_id}' from '{entrypoint}'. "
            f"Tried kwargs: {sorted(filtered_kwargs.keys())}. Original error: {e}"
        )

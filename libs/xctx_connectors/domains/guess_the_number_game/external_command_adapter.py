"""Domain-owned Guess the Number smoke adapter."""

from __future__ import annotations

import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _runtime_root(context: Any) -> Path:
    configured = os.environ.get("XCTX_RUNTIME_DIR")
    root = Path(configured) if configured else context.workspace_root / ".xctx_runtime"
    if not root.is_absolute():
        root = context.workspace_root / root
    return root


def _game_dir(context: Any) -> Path:
    return _runtime_root(context) / "guess_the_number_game" / "games"


def _result_digest(result_id: str) -> str:
    prefix = "result:"
    value = str(result_id).strip().lower()
    if not value.startswith(prefix):
        raise ValueError("game result must use result:<sha256>")
    digest = value[len(prefix) :]
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("game result must use result:<sha256>")
    return digest


def _game_path(context: Any, result_id: str) -> Path:
    return _game_dir(context) / f"{_result_digest(result_id)}.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_game(context: Any, result_id: str) -> dict[str, Any]:
    path = _game_path(context, result_id)
    if not path.exists():
        raise ValueError(f"unknown game result handle: {result_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid game state for: {result_id}")
    return payload


def _option(args: list[str], flag: str, *, required: bool = True) -> str | None:
    if flag not in args:
        if required:
            raise ValueError(f"missing {flag}")
        return None
    index = args.index(flag)
    if index + 1 >= len(args):
        raise ValueError(f"missing value for {flag}")
    return args[index + 1]


def _int_option(args: list[str], flag: str) -> int:
    raw = _option(args, flag)
    try:
        return int(str(raw))
    except ValueError as exc:
        raise ValueError(f"{flag} requires an integer") from exc


def _xctx_context(args: list[str]) -> dict[str, str]:
    return {
        "plan_id": str(_option(args, "--xctx-plan-id")),
        "commit_id": str(_option(args, "--xctx-commit-id")),
        "result_id": str(_option(args, "--xctx-result-id")),
    }


def _midpoint(low: int, high: int) -> int | None:
    return None if low > high else (low + high) // 2


def _discover(context: Any) -> dict[str, Any]:
    ref = context.adapter_ref
    if context.subdomain_id == "choose_random_number":
        next_moves = [
            f"./xctx plan {ref}::choose_between_bounds --minimum 1 --maximum 1000",
            "./xctx execute plan:sha256:<sha256> --commit",
            "./xctx observe result:<sha256>",
        ]
        return {
            "object_type": "guess_the_number_number_picker_discovery",
            "description": "Plan a committed write that creates a hidden number and returns a game result handle.",
            "planned_effects": [
                {
                    "action": "choose_between_bounds",
                    "run_cmd": f"./xctx plan {ref}::choose_between_bounds --minimum 1 --maximum 1000",
                }
            ],
            "next_moves": next_moves,
            "data_boundary": "Discovery describes the planned write. The hidden number is created only by execute --commit.",
        }
    next_moves = [
        f"./xctx plan {ref}::submit_guess --game-result result:<sha256> --guess 500",
        "./xctx execute plan:sha256:<sha256> --commit",
        "./xctx observe result:<sha256>",
    ]
    return {
        "object_type": "guess_the_number_guess_discovery",
        "description": "Plan a committed guess against a previously created game result handle.",
        "planned_effects": [
            {
                "action": "submit_guess",
                "run_cmd": f"./xctx plan {ref}::submit_guess --game-result result:<sha256> --guess 500",
            }
        ],
        "next_moves": next_moves,
        "data_boundary": "Guess feedback is returned through the committed result handle.",
    }


def _choose_between_bounds(context: Any, args: list[str]) -> dict[str, Any]:
    low = _int_option(args, "--minimum")
    high = _int_option(args, "--maximum")
    if low > high:
        raise ValueError("--minimum must be less than or equal to --maximum")
    xctx = _xctx_context(args)
    result_id = xctx["result_id"]
    secret = random.randint(low, high)
    now = _now()
    game = {
        "game_result_id": result_id,
        "created_at": now,
        "range": {"min": low, "max": high},
        "current_range": {"min": low, "max": high},
        "secret_number": secret,
        "attempts": [],
        "status": "active",
        "created_by": {
            "plan_id": xctx["plan_id"],
            "commit_id": xctx["commit_id"],
        },
    }
    _write_json(_game_path(context, result_id), game)
    first_guess = _midpoint(low, high)
    return {
        "object_type": "guess_the_number_game_created",
        "game_result_id": result_id,
        "status": "active",
        "range": {"min": low, "max": high},
        "attempt_count": 0,
        "next_guess": first_guess,
        "next_plan_command": (
            f"./xctx plan guess_the_number_game::guess_number::submit_guess "
            f"--game-result {result_id} --guess {first_guess}"
            if first_guess is not None
            else None
        ),
        "data_boundary": "The hidden number is remembered by the domain adapter and is not returned in this payload.",
    }


def _validate_choose_between_bounds(context: Any, args: list[str]) -> dict[str, Any]:
    low = _int_option(args, "--minimum")
    high = _int_option(args, "--maximum")
    if low > high:
        return {
            "ok": False,
            "error": "--minimum must be less than or equal to --maximum",
        }
    return {
        "ok": True,
        "object_type": "guess_the_number_plan_preflight",
    }


def _submit_guess(context: Any, args: list[str]) -> dict[str, Any]:
    game_result = str(_option(args, "--game-result"))
    guess = _int_option(args, "--guess")
    xctx = _xctx_context(args)
    game = _read_game(context, game_result)
    secret = int(game["secret_number"])
    current = dict(game.get("current_range") or game.get("range") or {})
    low = int(current.get("min", game.get("range", {}).get("min", 0)))
    high = int(current.get("max", game.get("range", {}).get("max", 0)))

    if guess == secret:
        feedback = "yes"
        correct = True
        next_range = {"min": guess, "max": guess}
        game["status"] = "solved"
    elif guess < secret:
        feedback = "higher"
        correct = False
        next_range = {"min": max(low, guess + 1), "max": high}
    else:
        feedback = "lower"
        correct = False
        next_range = {"min": low, "max": min(high, guess - 1)}

    attempt = {
        "guess_result_id": xctx["result_id"],
        "plan_id": xctx["plan_id"],
        "commit_id": xctx["commit_id"],
        "guess": guess,
        "feedback": feedback,
        "correct": correct,
        "created_at": _now(),
    }
    attempts = list(game.get("attempts") or [])
    attempts.append(attempt)
    game["attempts"] = attempts
    game["current_range"] = next_range
    game["updated_at"] = attempt["created_at"]
    _write_json(_game_path(context, game_result), game)

    next_guess = None if correct else _midpoint(int(next_range["min"]), int(next_range["max"]))
    next_plan_command = (
        None
        if next_guess is None
        else (
            "./xctx plan guess_the_number_game::guess_number::submit_guess "
            f"--game-result {game_result} --guess {next_guess}"
        )
    )
    return {
        "object_type": "guess_the_number_guess_feedback",
        "game_result_id": game_result,
        "guess_result_id": xctx["result_id"],
        "guess": guess,
        "correct": correct,
        "feedback": feedback,
        "next_range": next_range,
        "attempt_count": len(attempts),
        "game_status": game["status"],
        "next_guess": next_guess,
        "next_plan_command": next_plan_command,
        "data_boundary": "Feedback says whether the hidden number is higher, lower, or yes; the hidden number is not exposed unless guessed correctly.",
    }


def _validate_submit_guess(context: Any, args: list[str]) -> dict[str, Any]:
    try:
        game_result = str(_option(args, "--game-result"))
        _result_digest(game_result)
        _read_game(context, game_result)
        _int_option(args, "--guess")
    except ValueError as exc:
        return {
            "ok": False,
            "error": str(exc),
        }
    return {
        "ok": True,
        "object_type": "guess_the_number_plan_preflight",
    }


def _observe(context: Any, args: list[str]) -> dict[str, Any]:
    target = " ".join(args).strip() or "status"
    return {
        "object_type": "guess_the_number_status",
        "target": target,
        "agent_subdomain": context.subdomain_id,
        "message": "Use protocol-local result handles for game creation and guess feedback.",
        "next_moves": [
            "./xctx observe result:<sha256>",
            "./xctx plan guess_the_number_game::choose_random_number::choose_between_bounds --minimum 1 --maximum 1000",
        ],
    }


def _audit(context: Any) -> dict[str, Any]:
    return {
        "object_type": "guess_the_number_audit",
        "checks": [
            {
                "id": f"audit:{context.domain_id}:{context.subdomain_id}:smoke_adapter_loaded",
                "status": "pass",
            }
        ],
    }


def run(context: Any, command: str, rest: list[str], runtime: Any) -> dict[str, Any]:
    if command == "discover":
        return _discover(context)
    if command == "audit":
        return _audit(context)
    if command == "observe":
        return _observe(context, rest)
    if command == "validate-choose-between-bounds":
        return _validate_choose_between_bounds(context, rest)
    if command == "choose-between-bounds":
        return _choose_between_bounds(context, rest)
    if command == "validate-submit-guess":
        return _validate_submit_guess(context, rest)
    if command == "submit-guess":
        return _submit_guess(context, rest)
    raise ValueError(f"unsupported guess_the_number_game command: {command}")

"""Session persistence shared by HTTP handlers and research tools."""

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def investor_profile(row: dict) -> dict:
    return {
        "watchlist": row["watchlist"] or [],
        "risk_tolerance": row["risk_tolerance"] or "moderate",
        "focus_metrics": row["focus_metrics"] or [],
    }


async def get_session(db: AsyncSession, session_id: str, *, lock: bool = False) -> dict | None:
    suffix = " FOR UPDATE" if lock else ""
    result = await db.execute(text(
        "SELECT session_id, watchlist, risk_tolerance, focus_metrics, "
        "message_history, updated_at FROM user_sessions WHERE session_id = :session_id" + suffix
    ), {"session_id": session_id})
    row = result.mappings().one_or_none()
    return dict(row) if row is not None else None


async def ensure_session(db: AsyncSession, session_id: str) -> dict:
    await db.execute(text("""
        INSERT INTO user_sessions (session_id) VALUES (:session_id)
        ON CONFLICT (session_id) DO NOTHING
    """), {"session_id": session_id})
    row = await get_session(db, session_id, lock=True)
    if row is None:
        raise RuntimeError("Session disappeared during initialization")
    return row


async def save_profile(
    db: AsyncSession, session_id: str, watchlist: list[str],
    risk_tolerance: str, focus_metrics: list[str],
) -> dict:
    result = await db.execute(text("""
        INSERT INTO user_sessions (session_id, watchlist, risk_tolerance, focus_metrics)
        VALUES (:session_id, CAST(:watchlist AS jsonb), :risk_tolerance, CAST(:focus_metrics AS jsonb))
        ON CONFLICT (session_id) DO UPDATE SET
            watchlist = EXCLUDED.watchlist,
            risk_tolerance = EXCLUDED.risk_tolerance,
            focus_metrics = EXCLUDED.focus_metrics,
            updated_at = NOW()
        RETURNING watchlist, risk_tolerance, focus_metrics
    """), {
        "session_id": session_id, "watchlist": json.dumps(watchlist),
        "risk_tolerance": risk_tolerance, "focus_metrics": json.dumps(focus_metrics),
    })
    return investor_profile(dict(result.mappings().one()))


async def append_turn(db: AsyncSession, session_id: str, message: str, summary: str) -> None:
    await db.execute(text("""
        UPDATE user_sessions
        SET message_history = COALESCE(message_history, CAST('[]' AS jsonb)) || CAST(:turn AS jsonb),
            updated_at = NOW()
        WHERE session_id = :session_id
    """), {
        "session_id": session_id,
        "turn": json.dumps([
            {"role": "user", "content": message},
            {"role": "assistant", "content": summary},
        ]),
    })

"""Tab Ore -- working days + per-day timetable slots.

Routes:
  - GET    /api/working-hours/config            -- full config bundle
  - GET    /api/working-hours/days              -- list active + inactive days
  - POST   /api/working-hours/days              -- create one day
  - PUT    /api/working-hours/days/{day_id}     -- patch a day
  - DELETE /api/working-hours/days/{day_id}     -- delete a day (+ slots)
  - PUT    /api/working-hours/days/{day_id}/slots -- replace day's slots
  - POST   /api/working-hours/reset             -- restore the lun-sab 8-14
                                                    default

The endpoint set is intentionally small: most users will edit the
configuration once via the Ore tab (a small N=7 days), so a coarse
"replace all slots in this day" PUT covers every realistic edit
without exposing slot-level CRUD.

The server publishes its config via the same router so the
frontend's WeeklyCalendarView can read the authoritative layout
(days + slot times) instead of the legacy hardcoded constants in
webui/frontend/src/lib/constants.ts.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..tenant import current_tenant_id


router = APIRouter(prefix="/api/working-hours", tags=["working-hours"])


_DEFAULT_DAYS = [
    ("MON", "Lunedi",    0, 1),
    ("TUE", "Martedi",   1, 2),
    ("WED", "Mercoledi", 2, 3),
    ("THU", "Giovedi",   3, 4),
    ("FRI", "Venerdi",   4, 5),
    ("SAT", "Sabato",    5, 6),
]


def _validate_hhmm(s: str) -> str:
    """Accept 'H:MM' or 'HH:MM' and normalise to 'HH:MM'. Raise on
    parse error; the router translates exceptions into 422."""
    parts = s.split(":")
    if len(parts) != 2:
        raise ValueError(
            f"Orario invalido: '{s}' (formato richiesto HH:MM)"
        )
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError as e:
        raise ValueError(
            f"Orario invalido: '{s}' (formato richiesto HH:MM)"
        ) from e
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(
            f"Orario fuori intervallo: '{s}' (00:00..23:59)"
        )
    return f"{h:02d}:{m:02d}"


def _hhmm_to_minutes(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _validate_slots(slots: list[schemas.WorkingHourSlotIn]) -> None:
    """Per-day invariants: at least 1 slot, monotone increasing,
    no overlap."""
    if not slots:
        raise ValueError("Almeno uno slot per ogni giorno lavorativo.")
    prev_end = -1
    for s in slots:
        try:
            start = _validate_hhmm(s.start_time)
            end = _validate_hhmm(s.end_time)
        except ValueError as e:
            raise ValueError(str(e)) from e
        sm = _hhmm_to_minutes(start)
        em = _hhmm_to_minutes(end)
        if em <= sm:
            raise ValueError(
                f"Lo slot {start}-{end} ha durata <= 0."
            )
        if sm < prev_end:
            raise ValueError(
                "Slot sovrapposti o non in ordine "
                f"(start={start} < prev end)"
            )
        prev_end = em


def _serialize_day(day: models.WorkingDay) -> schemas.WorkingDayOut:
    return schemas.WorkingDayOut(
        id=day.id,
        code=day.code,
        label=day.label,
        position=day.position,
        legacy_day_number=day.legacy_day_number,
        is_active=day.is_active,
        slots=[
            schemas.WorkingHourSlotOut(
                id=s.id,
                day_id=s.day_id,
                slot_index=s.slot_index,
                start_time=s.start_time,
                end_time=s.end_time,
                label=s.label,
                legacy_hour_number=s.legacy_hour_number,
            )
            for s in sorted(day.slots, key=lambda x: x.slot_index)
        ],
    )


# ---------- GET /config (aggregate) ----------


@router.get("/config", response_model=schemas.WorkingHoursConfigOut)
def get_config(
    db: Session = Depends(get_db),
    tid: int = Depends(current_tenant_id),
):
    days = (
        db.query(models.WorkingDay)
        .filter(models.WorkingDay.tenant_id == tid)
        .order_by(models.WorkingDay.position)
        .all()
    )
    out_days = [_serialize_day(d) for d in days]
    active = [d for d in out_days if d.is_active]
    counts = [len(d.slots) for d in active]
    max_slots = max(counts) if counts else 0
    uniform = all(c == max_slots for c in counts) if counts else True
    return schemas.WorkingHoursConfigOut(
        days=out_days,
        max_slots_per_day=max_slots,
        uniform_slot_count=uniform,
    )


# ---------- Days CRUD ----------


@router.get("/days", response_model=list[schemas.WorkingDayOut])
def list_days(
    db: Session = Depends(get_db),
    tid: int = Depends(current_tenant_id),
):
    rows = (
        db.query(models.WorkingDay)
        .filter(models.WorkingDay.tenant_id == tid)
        .order_by(models.WorkingDay.position)
        .all()
    )
    return [_serialize_day(d) for d in rows]


@router.post("/days", response_model=schemas.WorkingDayOut)
def create_day(
    payload: schemas.WorkingDayIn,
    db: Session = Depends(get_db),
    tid: int = Depends(current_tenant_id),
):
    d = models.WorkingDay(
        tenant_id=tid,
        code=payload.code.upper(),
        label=payload.label,
        position=payload.position,
        legacy_day_number=payload.legacy_day_number,
        is_active=payload.is_active,
    )
    db.add(d)
    try:
        db.commit()
        db.refresh(d)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            400, f"Giorno non creato: {e}") from e
    return _serialize_day(d)


@router.put("/days/{day_id}", response_model=schemas.WorkingDayOut)
def update_day(
    day_id: int,
    payload: schemas.WorkingDayPatch,
    db: Session = Depends(get_db),
    tid: int = Depends(current_tenant_id),
):
    d = (
        db.query(models.WorkingDay)
        .filter(models.WorkingDay.id == day_id,
                models.WorkingDay.tenant_id == tid)
        .first()
    )
    if d is None:
        raise HTTPException(404, f"WorkingDay {day_id} non trovato")
    fields = payload.model_dump(exclude_unset=True)
    if "code" in fields and fields["code"] is not None:
        fields["code"] = fields["code"].upper()
    for k, v in fields.items():
        setattr(d, k, v)
    try:
        db.commit()
        db.refresh(d)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            400, f"Giorno non aggiornato: {e}") from e
    return _serialize_day(d)


@router.delete("/days/{day_id}")
def delete_day(
    day_id: int,
    db: Session = Depends(get_db),
    tid: int = Depends(current_tenant_id),
):
    d = (
        db.query(models.WorkingDay)
        .filter(models.WorkingDay.id == day_id,
                models.WorkingDay.tenant_id == tid)
        .first()
    )
    if d is None:
        raise HTTPException(404, f"WorkingDay {day_id} non trovato")
    db.delete(d)
    db.commit()
    return {"ok": True, "deleted_id": day_id}


@router.put("/days/{day_id}/slots",
            response_model=schemas.WorkingDayOut)
def replace_day_slots(
    day_id: int,
    payload: schemas.WorkingDaySlotsReplace,
    db: Session = Depends(get_db),
    tid: int = Depends(current_tenant_id),
):
    d = (
        db.query(models.WorkingDay)
        .filter(models.WorkingDay.id == day_id,
                models.WorkingDay.tenant_id == tid)
        .first()
    )
    if d is None:
        raise HTTPException(404, f"WorkingDay {day_id} non trovato")
    try:
        _validate_slots(payload.slots)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    db.query(models.WorkingHourSlot) \
        .filter(models.WorkingHourSlot.day_id == day_id).delete()
    for idx, s in enumerate(payload.slots):
        new = models.WorkingHourSlot(
            day_id=day_id,
            slot_index=idx,
            start_time=_validate_hhmm(s.start_time),
            end_time=_validate_hhmm(s.end_time),
            label=s.label,
            legacy_hour_number=s.legacy_hour_number,
        )
        db.add(new)
    try:
        db.commit()
        db.refresh(d)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            400, f"Slot non aggiornati: {e}") from e
    return _serialize_day(d)


# ---------- Reset to default ----------


@router.post("/reset")
def reset_to_default(
    db: Session = Depends(get_db),
    tid: int = Depends(current_tenant_id),
):
    """Drop every WorkingDay/Slot for this tenant and re-seed the
    canonical lun-sab + 8:00-14:00 configuration. Useful when a
    tenant accidentally botches the Ore tab and wants to start over.
    """
    db.query(models.WorkingHourSlot).filter(
        models.WorkingHourSlot.day_id.in_(
            db.query(models.WorkingDay.id)
            .filter(models.WorkingDay.tenant_id == tid)
        )
    ).delete(synchronize_session=False)
    db.query(models.WorkingDay).filter(
        models.WorkingDay.tenant_id == tid
    ).delete(synchronize_session=False)
    for code, label, pos, legacy in _DEFAULT_DAYS:
        d = models.WorkingDay(
            tenant_id=tid,
            code=code, label=label, position=pos,
            legacy_day_number=legacy, is_active=True,
        )
        db.add(d)
        db.flush()
        for i in range(6):
            h = 8 + i
            db.add(models.WorkingHourSlot(
                day_id=d.id,
                slot_index=i,
                start_time=f"{h:02d}:00",
                end_time=f"{h+1:02d}:00",
                label=f"{i+1}ª ora",
                legacy_hour_number=h,
            ))
    db.commit()
    return {"ok": True}

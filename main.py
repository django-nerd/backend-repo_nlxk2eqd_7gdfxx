import os
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, Path, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents

app = FastAPI(title="Jo's Time Tracker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helper utilities

def to_object_id(id_str: str):
    from bson.objectid import ObjectId  # available via pymongo
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id format")


def compute_worked_minutes(start: datetime, end: Optional[datetime], break_minutes: int) -> int:
    if end is None:
        end = datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    diff = int((end - start).total_seconds() // 60)
    return max(0, diff - (break_minutes or 0))


# Request models

class ClientIn(BaseModel):
    name: str
    notes: Optional[str] = None


class ProjectIn(BaseModel):
    name: str
    client_id: str
    notes: Optional[str] = None


class TimeEntryIn(BaseModel):
    client_id: str
    project_id: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    break_minutes: int = 0
    hourly_rate: Optional[float] = None
    notes: Optional[str] = None


class SettingsIn(BaseModel):
    theme: str = "system"
    timezone: str = "UTC"
    language: str = "en"
    date_format: str = "yyyy-MM-dd"


@app.get("/")
def read_root():
    return {"message": "Jo's Time Tracker backend is running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
                response["connection_status"] = "Connected"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


# Settings (single document collection: "settings")
@app.get("/api/settings")
def get_settings():
    doc = db["settings"].find_one({}) if db else None
    if not doc:
        return SettingsIn().model_dump()
    doc.pop("_id", None)
    return doc


@app.put("/api/settings")
def update_settings(payload: SettingsIn):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    db["settings"].update_one({}, {"$set": payload.model_dump()}, upsert=True)
    return payload.model_dump()


# Clients
@app.post("/api/clients")
def create_client(payload: ClientIn):
    existing = db["client"].find_one({"name": payload.name}) if db else None
    if existing:
        raise HTTPException(status_code=409, detail="Client already exists")
    new_id = create_document("client", payload.model_dump())
    return {"_id": new_id}


@app.get("/api/clients")
def list_clients(q: Optional[str] = Query(None, description="Typeahead query")):
    flt = {"name": {"$regex": q, "$options": "i"}} if q else {}
    docs = get_documents("client", flt)
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


# Projects
@app.post("/api/projects")
def create_project(payload: ProjectIn):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    if db["client"].count_documents({"_id": to_object_id(payload.client_id)}) == 0:
        raise HTTPException(status_code=404, detail="Client not found")
    new_id = create_document("project", payload.model_dump())
    return {"_id": new_id}


@app.get("/api/projects")
def list_projects(client_id: Optional[str] = None, q: Optional[str] = None):
    flt = {}
    if client_id:
        flt["client_id"] = client_id
    if q:
        flt["name"] = {"$regex": q, "$options": "i"}
    docs = get_documents("project", flt)
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


# Time Entries
@app.post("/api/time-entries")
def create_time_entry(payload: TimeEntryIn):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    if db["client"].count_documents({"_id": to_object_id(payload.client_id)}) == 0:
        raise HTTPException(status_code=404, detail="Client not found")
    if payload.project_id:
        if db["project"].count_documents({"_id": to_object_id(payload.project_id)}) == 0:
            raise HTTPException(status_code=404, detail="Project not found")

    data = payload.model_dump()
    worked_minutes = compute_worked_minutes(payload.start_time, payload.end_time, payload.break_minutes or 0)
    data["worked_minutes"] = worked_minutes

    new_id = create_document("timeentry", data)
    return {"_id": new_id, "worked_minutes": worked_minutes}


@app.get("/api/time-entries")
def list_time_entries(month: Optional[str] = None, client_id: Optional[str] = None):
    flt = {}
    if client_id:
        flt["client_id"] = client_id
    if month:
        try:
            year, mon = map(int, month.split("-"))
            start = datetime(year, mon, 1, tzinfo=timezone.utc)
            end = datetime(year + (1 if mon == 12 else 0), 1 if mon == 12 else mon + 1, 1, tzinfo=timezone.utc)
            flt["start_time"] = {"$gte": start, "$lt": end}
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid month format; expected YYYY-MM")

    docs = get_documents("timeentry", flt)
    for d in docs:
        d["_id"] = str(d["_id"])
        start = d.get("start_time")
        end = d.get("end_time")
        break_min = d.get("break_minutes", 0)
        try:
            worked = compute_worked_minutes(start, end, break_min)
        except Exception:
            worked = d.get("worked_minutes", 0)
        d["worked_minutes"] = worked
    docs.sort(key=lambda x: x.get("start_time", datetime.min), reverse=True)
    return docs


@app.patch("/api/time-entries/{entry_id}")
def update_time_entry(entry_id: str, payload: dict = Body(...)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    # sanitize fields
    allowed = {"start_time", "end_time", "break_minutes", "hourly_rate", "notes", "client_id", "project_id"}
    update = {k: v for k, v in payload.items() if k in allowed}
    if not update:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    db["timeentry"].update_one({"_id": to_object_id(entry_id)}, {"$set": update})
    doc = db["timeentry"].find_one({"_id": to_object_id(entry_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Time entry not found")
    # recompute worked minutes
    worked = compute_worked_minutes(doc.get("start_time"), doc.get("end_time"), doc.get("break_minutes", 0))
    db["timeentry"].update_one({"_id": to_object_id(entry_id)}, {"$set": {"worked_minutes": worked}})
    doc["_id"] = str(doc["_id"])
    doc["worked_minutes"] = worked
    return doc


@app.post("/api/punch/start")
def punch_start(client_id: str, project_id: Optional[str] = None, notes: Optional[str] = None):
    now = datetime.now(timezone.utc)
    payload = TimeEntryIn(client_id=client_id, project_id=project_id, start_time=now, end_time=None, notes=notes)
    return create_time_entry(payload)


@app.post("/api/punch/stop")
def punch_stop():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    doc = db["timeentry"].find_one({"end_time": None}, sort=[("start_time", -1)])
    if not doc:
        raise HTTPException(status_code=404, detail="No running timer")
    end = datetime.now(timezone.utc)
    worked = compute_worked_minutes(doc.get("start_time"), end, doc.get("break_minutes", 0))
    db["timeentry"].update_one({"_id": doc["_id"]}, {"$set": {"end_time": end, "worked_minutes": worked}})
    doc = db["timeentry"].find_one({"_id": doc["_id"]})
    doc["_id"] = str(doc["_id"])
    doc["worked_minutes"] = worked
    return doc


@app.get("/api/summary")
def get_summary():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=day_start.weekday())
    month_start = day_start.replace(day=1)
    if month_start.month == 1:
        prev_month_start = month_start.replace(year=month_start.year - 1, month=12)
    else:
        prev_month_start = month_start.replace(month=month_start.month - 1)
    if month_start.month == 12:
        next_month_start = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month_start = month_start.replace(month=month_start.month + 1)

    ranges = {
        "today": (day_start, day_start + timedelta(days=1)),
        "week": (week_start, week_start + timedelta(days=7)),
        "month": (month_start, next_month_start),
        "prev_month": (prev_month_start, month_start),
    }

    result = {}
    for key, (start, end) in ranges.items():
        cursor = db["timeentry"].find({"start_time": {"$gte": start, "$lt": end}})
        total = 0
        for d in cursor:
            total += compute_worked_minutes(d.get("start_time"), d.get("end_time"), d.get("break_minutes", 0))
        result[key] = total

    return result


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

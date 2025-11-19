"""
Database Schemas for Jo's Time Tracker

Each Pydantic model maps to a MongoDB collection with the lowercase class name.
"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class Client(BaseModel):
    name: str = Field(..., description="Client name")
    notes: Optional[str] = Field(None, description="Optional notes about the client")

class Project(BaseModel):
    name: str = Field(..., description="Project name")
    client_id: str = Field(..., description="Reference to client _id as string")
    notes: Optional[str] = Field(None, description="Optional notes about the project")

class TimeEntry(BaseModel):
    client_id: str = Field(..., description="Reference to client _id as string")
    project_id: Optional[str] = Field(None, description="Reference to project _id as string")
    start_time: datetime = Field(..., description="Start datetime in ISO format")
    end_time: Optional[datetime] = Field(None, description="End datetime in ISO format; null means running")
    break_minutes: int = Field(0, ge=0, description="Break duration in minutes")
    hourly_rate: Optional[float] = Field(None, ge=0, description="Optional hourly rate for this entry")
    notes: Optional[str] = Field(None, description="Notes for this time entry")

class Settings(BaseModel):
    theme: str = Field("system", description="light | dark | system")
    timezone: str = Field("UTC", description="IANA timezone string, e.g., 'America/Los_Angeles'")
    language: str = Field("en", description="ISO language code")
    date_format: str = Field("yyyy-MM-dd", description="Date display format")

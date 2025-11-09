from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import os
from dotenv import load_dotenv
from urllib.parse import quote_plus

# Load environment variables
load_dotenv()

# FastAPI app
app = FastAPI(title="TaskFlow API", version="1.0.0")

# CORS middleware for cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace "*" with your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB connection with escaped credentials
username = quote_plus(os.getenv("MONGO_USER"))
password = quote_plus(os.getenv("MONGO_PASS"))
cluster = os.getenv("MONGO_CLUSTER")
db_name = os.getenv("MONGO_DB")  # e.g., "taskflow_db"

MONGO_URI = f"mongodb+srv://{username}:{password}@{cluster}/{db_name}?retryWrites=true&w=majority"

client = AsyncIOMotorClient(MONGO_URI)
db = client[db_name]
tasks_collection = db.tasks

print("Connected to MongoDB successfully!")

# Pydantic models
class TaskBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    deadline: Optional[str] = None
    status: str = Field(default="not-done", pattern="^(done|pending|not-done|dropped)$")

class TaskCreate(TaskBase):
    pass

class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    deadline: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(done|pending|not-done|dropped)$")

class TaskResponse(TaskBase):
    id: str = Field(alias="_id")
    created_at: str
    last_updated: str

    class Config:
        populate_by_name = True

# Helper function to serialize MongoDB documents
def task_helper(task) -> dict:
    return {
        "_id": str(task["_id"]),
        "title": task["title"],
        "description": task.get("description"),
        "deadline": task.get("deadline"),
        "status": task["status"],
        "created_at": task["created_at"],
        "last_updated": task["last_updated"]
    }

@app.on_event("startup")
async def startup_db_client():
    """Initialize database connection on startup"""
    try:
        # Test connection
        await client.admin.command('ping')
        print("✅ Connected to MongoDB successfully")
    except Exception as e:
        print(f"❌ Failed to connect to MongoDB: {e}")

@app.on_event("shutdown")
async def shutdown_db_client():
    """Close database connection on shutdown"""
    client.close()
    print("🔌 Disconnected from MongoDB")

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "online",
        "message": "TaskFlow API is running",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/tasks", response_model=List[TaskResponse])
async def get_tasks():
    """Retrieve all tasks"""
    tasks = []
    async for task in tasks_collection.find():
        tasks.append(task_helper(task))
    return tasks

@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str):
    """Retrieve a specific task by ID"""
    if not ObjectId.is_valid(task_id):
        raise HTTPException(status_code=400, detail="Invalid task ID format")
    
    task = await tasks_collection.find_one({"_id": ObjectId(task_id)})
    if task:
        return task_helper(task)
    raise HTTPException(status_code=404, detail="Task not found")

@app.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(task: TaskCreate):
    """Create a new task"""
    now = datetime.utcnow().isoformat()
    
    task_dict = {
        "title": task.title,
        "description": task.description,
        "deadline": task.deadline,
        "status": task.status,
        "created_at": now,
        "last_updated": now
    }
    
    result = await tasks_collection.insert_one(task_dict)
    created_task = await tasks_collection.find_one({"_id": result.inserted_id})
    
    return task_helper(created_task)

@app.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(task_id: str, task_update: TaskUpdate):
    """Update an existing task"""
    if not ObjectId.is_valid(task_id):
        raise HTTPException(status_code=400, detail="Invalid task ID format")
    
    # Build update dictionary with only provided fields
    update_dict = {k: v for k, v in task_update.dict(exclude_unset=True).items() if v is not None}
    
    if not update_dict:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    # Add last_updated timestamp
    update_dict["last_updated"] = datetime.utcnow().isoformat()
    
    result = await tasks_collection.update_one(
        {"_id": ObjectId(task_id)},
        {"$set": update_dict}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    
    updated_task = await tasks_collection.find_one({"_id": ObjectId(task_id)})
    return task_helper(updated_task)

@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a task"""
    if not ObjectId.is_valid(task_id):
        raise HTTPException(status_code=400, detail="Invalid task ID format")
    
    result = await tasks_collection.delete_one({"_id": ObjectId(task_id)})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return {"message": "Task deleted successfully", "id": task_id}



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
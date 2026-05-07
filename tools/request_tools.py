
# -- Lead-specific protocol handlers --
import json
import time
import uuid

from tools.message_bus import BUS
from tools.request_store import REQUEST_STORE


def handle_shutdown_request(teammate: str) -> str:
    req_id = str(uuid.uuid4())[:8]
    REQUEST_STORE.create({
        "request_id": req_id,
        "kind": "shutdown",
        "from": "lead",
        "to": teammate,
        "status": "pending",
        "created_at": time.time(),
        "updated_at": time.time(),
    })
    BUS.send(
        "lead", teammate, "Please shut down gracefully.",
        "shutdown_request", {"request_id": req_id},
    )
    return f"Shutdown request {req_id} sent to '{teammate}' (status: pending)"

def handle_plan_review(request_id: str, approve: bool, feedback: str = "") -> str:
    req = REQUEST_STORE.get(request_id)
    if not req:
        return f"Error: Unknown plan request_id '{request_id}'"
    REQUEST_STORE.update(
        request_id,
        status="approved" if approve else "rejected",
        reviewed_by="lead",
        resolved_at=time.time(),
        feedback=feedback,
    )
    BUS.send(
        "lead", req["from"], feedback, "plan_approval_response",
        {"request_id": request_id, "approve": approve, "feedback": feedback},
    )
    return f"Plan {'approved' if approve else 'rejected'} for '{req['from']}'"

def _check_shutdown_status(request_id: str) -> str:
    return json.dumps(REQUEST_STORE.get(request_id) or {"error": "not found"})

###子任务的工具函数
def sub_shutdown_response(sender: str,  args: dict):
    req_id = args["request_id"]
    approve = args["approve"]
    updated = REQUEST_STORE.update(
        req_id,
        status="approved" if approve else "rejected",
        resolved_by=sender,
        resolved_at=time.time(),
        response={"approve": approve, "reason": args.get("reason", "")},
    )
    if not updated:
        return f"Error: Unknown shutdown request {req_id}"
    BUS.send(
        sender, "lead", args.get("reason", ""),
        "shutdown_response", {"request_id": req_id, "approve": approve},
    )
    return f"Shutdown {'approved' if approve else 'rejected'}"

def sub_plan_approval(sender: str, args: dict):
    plan_text = args.get("plan", "")
    req_id = str(uuid.uuid4())[:8]
    REQUEST_STORE.create({
        "request_id": req_id,
        "kind": "plan_approval",
        "from": sender,
        "to": "lead",
        "status": "pending",
        "plan": plan_text,
        "created_at": time.time(),
        "updated_at": time.time(),
    })
    BUS.send(
        sender, "lead", plan_text, "plan_approval",
        {"request_id": req_id, "plan": plan_text},
    )
    return f"Plan submitted (request_id={req_id}). Waiting for lead approval."
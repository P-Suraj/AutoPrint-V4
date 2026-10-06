"""Customer-facing text for each job status.

Decision O-8: say "Sent to printer", never "Printed", until the Phase 1 spike proves what
completion evidence the printers give us. Changing any wording here is a product decision.
"""
from app.schemas import JobStatus

CUSTOMER_MESSAGE: dict[JobStatus, str] = {
    JobStatus.awaiting_approval: "Waiting for the shop to approve your print.",
    JobStatus.approved: "Approved. Waiting for the printer.",
    JobStatus.printing: "Sending to the printer.",
    JobStatus.completed: "Sent to printer. Collect it at the counter.",
    JobStatus.failed: "The shop could not print this. Please ask at the counter.",
    JobStatus.needs_attention: "The shop is checking this print. Please ask at the counter.",
    JobStatus.rejected: "The shop declined this print.",
    JobStatus.cancelled: "Cancelled.",
    JobStatus.expired: "The shop did not approve this in time. Please start a new order.",
}

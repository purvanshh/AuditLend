from worker.celery_app import celery_app


@celery_app.task(bind=True, max_retries=0)
def process_application(self, application_id: str) -> dict[str, str]:
    return {"application_id": application_id, "status": "PENDING"}

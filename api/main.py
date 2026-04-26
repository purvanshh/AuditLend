from fastapi import FastAPI


app = FastAPI(title="AuditLend API", version="2.0.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy", "service": "auditlend-api", "version": "2.0.0"}

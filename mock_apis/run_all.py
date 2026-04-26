import multiprocessing

import uvicorn


SERVICES = [
    ("mock_apis.credit_bureau:app", 8001),
    ("mock_apis.bank_analyzer:app", 8002),
    ("mock_apis.gst_verifier:app", 8003),
]


def _run(app_path: str, port: int) -> None:
    uvicorn.run(app_path, host="0.0.0.0", port=port, log_level="info")


def main() -> None:
    processes = [
        multiprocessing.Process(target=_run, args=(app_path, port), daemon=False)
        for app_path, port in SERVICES
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join()


if __name__ == "__main__":
    main()

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from orchestrator import BRIEF_NAME, run_pipeline

app = FastAPI(title="BS Detector")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5175"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DOCUMENTS_DIR = Path(__file__).parent / "documents"


def load_documents() -> dict[str, str]:
    """Load all documents from the documents directory."""
    documents = {}
    for file_path in DOCUMENTS_DIR.glob("*.txt"):
        documents[file_path.stem] = file_path.read_text()
    return documents


@app.post("/analyze")
def analyze():
    documents = load_documents()
    if BRIEF_NAME not in documents:
        raise HTTPException(
            status_code=500, detail=f"{BRIEF_NAME}.txt not found in documents/"
        )
    report = run_pipeline(documents)
    body = {"report": report.model_dump()}
    if report.pipeline_status == "failed":
        return JSONResponse(status_code=503, content=body)
    return body

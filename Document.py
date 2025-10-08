from fastapi import FastAPI, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import io, os
from uuid import uuid4
from PyPDF2 import PdfReader
from docx import Document
from dotenv import load_dotenv
from google import genai  

# Load environment variables
load_dotenv()

# ✅ Create FastAPI app
app = FastAPI()

# ✅ Enable CORS (Frontend ↔ Backend connection)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Configure the Gemini Client
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ✅ Setup Jinja2 templates for frontend
Template = Jinja2Templates(directory="Template")


@app.get("/", response_class=HTMLResponse)
async def serve_frontend(request: Request):
    return Template.TemplateResponse("index.html", {"request": request})


# Test route
@app.get("/ping")
def ping():
    return {"message": "ping"}


# ✅ Store uploaded documents in memory
documents = {}


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload and extract text from PDF, DOCX, or TXT files."""
    filename = file.filename or "unnamed"
    content = await file.read()
    text = ""

    try:
        # PDF
        if filename.lower().endswith(".pdf"):
            reader = PdfReader(io.BytesIO(content))
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"

        # DOCX
        elif filename.lower().endswith(".docx"):
            doc = Document(io.BytesIO(content))
            for para in doc.paragraphs:
                if para.text:
                    text += para.text + "\n"

        # TXT
        elif filename.lower().endswith(".txt"):
            text = content.decode("utf-8", errors="ignore")

        else:
            return {"error": "Unsupported file type. Use .pdf, .docx, or .txt"}

    except Exception as e:
        return {"error": f"Failed to extract text: {str(e)}"}

    doc_id = str(uuid4())
    documents[doc_id] = {"filename": filename, "text": text}

    return {"doc_id": doc_id, "filename": filename}


@app.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    """Fetch uploaded document text."""
    doc = documents.get(doc_id)
    if not doc:
        return {"error": "Document not found"}
    return {"doc_id": doc_id, "filename": doc["filename"], "text": doc["text"]}


# ✅ Helper function: chunk text
def chunk_text(text, max_tokens=3000):
    """Split text into smaller chunks for long document summaries."""
    words = text.split()
    max_words_per_chunk = int(max_tokens * 0.75)
    for i in range(0, len(words), max_words_per_chunk):
        yield " ".join(words[i:i + max_words_per_chunk])


# ✅ Document Summarization Route
@app.get("/summary/{doc_id}")
async def summarize_document(doc_id: str):
    doc = documents.get(doc_id)
    if not doc:
        return {"error": "Document not found"}

    text = doc["text"]
    if not text.strip():
        return {"error": "Document contains no text to summarize."}

    try:
        # Short documents — summarize directly
        if len(text.split()) < 10000:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=f"Summarize this text clearly and concisely:\n\n{text}",
            )
            summary = response.text

        # Long documents — summarize in chunks
        else:
            partial_summaries = []
            for i, chunk in enumerate(chunk_text(text)):
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=f"Summarize Section {i+1} clearly for a final combination:\n\n{chunk}",
                )
                partial_summaries.append(response.text)

            combined_summary = " ".join(partial_summaries)
            final_response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=f"Combine these partial summaries into one final summary:\n\n{combined_summary}",
            )
            summary = final_response.text

        if not summary.strip():
            return {"error": "Gemini returned an empty summary."}

        return {"summary": summary}

    except Exception as e:
        print(f"Error summarizing document {doc_id}: {e}")
        return {"error": f"Failed to generate summary: {str(e)}"}


# ✅ Document Question Answering Route
@app.post("/query/{doc_id}")
async def query_document(doc_id: str, question: dict):
    doc = documents.get(doc_id)
    if not doc:
        return {"error": "Document not found"}

    text = doc["text"]
    user_question = question.get("query")
    if not user_question:
        return {"error": "Request body must include a 'query' field."}

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"You are a helpful assistant. Based ONLY on the following document:\n\n{text}\n\nAnswer this question:\n\n{user_question}",
        )
        return {"answer": response.text}

    except Exception as e:
        return {"error": str(e)}

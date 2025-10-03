from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
import io
import google.generativeai as genai
import os
from uuid import uuid4
from PyPDF2 import PdfReader
from docx import Document
from transformers import pipeline
from fastapi.templating import Jinja2Templates
from fastapi import Request
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv




# Created Backend app(app intsance) 
app = FastAPI()

# ✅ Enable CORS so frontend (HTML/JS) can access backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],  
    allow_headers=["*"],  
)

# Configure the Gemini SDK with your API key

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
gemini_model = genai.GenerativeModel("gemini-pro")

# Tell FastAPI where to find your HTML files
Template = Jinja2Templates(directory="Template")

@app.get("/", response_class=HTMLResponse)
async def serve_frontend(request: Request):
    return Template.TemplateResponse("index.html", {"request": request})

#Test route to confirm it works
@app.get("/ping")
def ping():
    return {"message": "ping"}

#Document Handling and Parsing

#Variable to store texts of each files
document = {}

@app.post("/upload") #This receives the file from Front end
async def upload_file(file: UploadFile = File(...)):
    #The Uploaded files name
    filename = file.filename or "unnamed" 
    content = await file.read() #Read the contents of the files in bytes
    text = ""

    try:
        # Handle PDF
        if filename.lower().endswith(".pdf"):
            from PyPDF2 import PdfReader
            reader = PdfReader(io.BytesIO(content))
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"

             # Handle DOCX
        elif filename.lower().endswith(".docx"):
            from docx import Document
            doc = Document(io.BytesIO(content))
            for para in doc.paragraphs:
                if para.text:
                    text += para.text + "\n"
               
               #Handle TxT
        elif filename.lower().endswith(".txt"):
            text = content.decode("utf-8", errors="ignore")

        else:
            return {"error": "Unsupported file type. Use .pdf, .docx or .txt"}

    except Exception as e:
        return {"error": f"Failed to extract text: {str(e)}"}
    
    # assign ID for this document
    doc_id = str(uuid4())
    document[doc_id] = {"filename": filename, "text": text}

    return {"doc_id": doc_id, "filename": filename}

# Route to fetch raw document text 
@app.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    doc = document.get(doc_id)
    if not doc:
        return {"error": "Document not found"}
    return {"doc_id": doc_id,"filename": doc["filename"], "text": doc["text"] }



#New Route in FastAPI
@app.get("/summary/{doc_id}")
async def summarize_document(doc_id: str):
    # Check if document exists
    doc = document.get(doc_id)
    if not doc:
        return {"error": "document not found"}
    
    text = doc["text"]

    try:
        response = gemini_model.generate_content(
            f"Summarize this text in a clear and concise way:\n\n{text}"
        )
        return {"summary": response.text}
    except Exception as e:
        return {"error": str(e)}
    
    #Chunk Text
def chunk_text(text, max_tokens=1000):
    """
    Break long text into smaller chunks (1500 words by default).
    """
    max_words = int(max_tokens * 0.75) 
    words = text.split()
    for i in range(0, len(words), max_words):
        yield " ".join(words[i:i + max_words])

        # If short, summarize directly
        if len(text.split()) < 30000: 
        

    # If long, break into chunks
         partial_summaries = []
    for i, chunk in enumerate(chunk_text(text)):
        response = gemini_model.generate_content(
                f"Summarize this Section {i+1} clearly for final combination:\n\n{chunk}"
            )
        partial_summaries.append(response.text)

    # Combine partial summaries
    combined_text = " ".join(partial_summaries)
    final_summary = gemini_model.generate_content(
            f"Combine the following partial summaries into one final, concise document summary:\n\n{combined_text}"
        )
        
    return {"summary": final_summary.text}

    #Questions about the Document

@app.post("/query/{doc_id}")
async def query_document(doc_id: str, question: dict):
    doc = document.get(doc_id)

    if not doc:
        return {"error": "Document not found"}

    text = doc["text"]

    user_question = question.get('query')
    if not user_question:
        return {"error": "Query body must include 'query' field."}

    try:
        response = gemini_model.generate_content(
            f"You are a helpful assistant. Based on this document:\n\n{text}\n\n"
             f"You are a helpful assistant. Based ONLY on the following document:\n\n{text}\n\n"
            f"Answer the following question clearly:\n\n{user_question}"
        )
        return {"answer": response.text} 
    except Exception as e:
        # This is the point where rate limits or API key issues are caught
        return {"error": str(e)}
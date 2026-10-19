# PhotoSearch

PhotoSearch is a desktop app for finding photos with natural-language searches. It builds a local index from image metadata and uses text embeddings to find photos whose descriptions match a request. For example, you can search for “family photos taken in Paris in the evening” or “find the color code written on the paint lid years ago.”

## How it works

PhotoSearch reads EXIF and embedded image metadata, including capture date, GPS location, keywords, title, and description. It combines that metadata into searchable text and stores its vector index locally. It does not use a vision model to inspect image contents itself; useful image descriptions and tags should be embedded in each photo's metadata.

For vision-based picture tagging, use [AIPhotoAssists](https://github.com/OsztosA/AIPhotoAssists), which uses an LLM with vision. A typical workflow is:

1. Use AIPhotoAssists to generate and write tags or descriptions to your photos' metadata.
2. Add the photo folders in PhotoSearch's **Settings**.
3. Click **Build / update EXIF DB** to read metadata, then **Build / update vector DB** to index descriptions.
4. Search using subjects, places, dates, or other details included in the metadata.

Rebuild the EXIF database after changing photo metadata. Update the vector database afterward to refresh the searchable embeddings.

## Requirements

- Python 3.10 or newer
- An OpenAI-compatible API endpoint that provides chat completions and text embeddings (for example, a local LLM server)
- An embedding model available from that endpoint

## Tested models and hardware

Tested with:

- [`text-embedding-nomic-embed-text-v1.5@f32`](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF) for text embeddings
- [Mistral Small 3.2](https://lmstudio.ai/models/mistralai/mistral-small-3.2) (Q4_K_M), used by the author to classify and tag photos with AIPhotoAssists

Tested on an AMD Ryzen 7 7700X with an AMD Radeon RX 7900 XT.

## Installation and launch

From the project folder, create and activate a virtual environment, then install the dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

If PowerShell blocks virtual-environment activation, run the commands using `.\.venv\Scripts\python.exe` instead; for example:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## Build a Windows executable

Build on Windows from the project folder. The script installs the build requirements and creates the executable. The build includes its Python runtime and application dependencies; Python is not required on machines running the built app.

```bat
build.bat
```

Run `dist\PhotoSearch\PhotoSearch.exe` or distribute the entire `dist\PhotoSearch` folder. The executable stores its configuration and default databases under `%LOCALAPPDATA%\PhotoSearch`; settings and indexed data are therefore kept separately from the built files.

## Configuration

Open **Settings...** from the app menu to configure:

- Photo folders and whether to scan subfolders
- The chat-completions endpoint and model used to parse search requests and optionally rerank results
- The embeddings endpoint and model used to index and search descriptions
- Search result limits and local database locations

The defaults expect OpenAI-compatible routes at `/v1/chat/completions` and `/v1/embeddings`. Set the base URLs to the corresponding server address, typically ending in `/v1`. Configure API keys there if your server requires them.

By default, the app scans JPEG and HEIC/HEIF images. The EXIF database and Chroma vector database are stored under `data/`. Configuration is saved in `config.json`.

## Search

Enter a natural-language request in the **Search** tab and click **Search** or press Enter. PhotoSearch uses metadata filters when a request specifies dates or times, then searches descriptions semantically and can ask the configured chat model to select the best matches. Select a result to view its description and preview.

## Credits

- [Nomic AI](https://huggingface.co/nomic-ai) for the Nomic Embed Text v1.5 embedding model.
- [Mistral AI](https://mistral.ai/) for Mistral Small 3.2.
- [LM Studio](https://lmstudio.ai/) for model distribution and local model serving.
- [AIPhotoAssists](https://github.com/OsztosA/AIPhotoAssists) for vision-based photo classification and tagging in the author's workflow.

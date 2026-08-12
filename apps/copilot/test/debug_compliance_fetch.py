"""
Standalone diagnostic for compliance_lookup_service.py -- isolates the
fetch from the whole RFC pipeline so we're not spending a full run (and
real OpenAI API cost) to debug one function.

Run from apps/copilot/:
    uv run --package copilot python3 test/debug_compliance_fetch.py
"""
import asyncio
import sys

sys.path.insert(0, "src")

from copilot.services.compliance_lookup_service import (
    VERIFIED_COMPLIANCE_DOCUMENTS,
    fetch_compliance_excerpt,
)


async def main():
    import httpx
    from pypdf import PdfReader
    import io

    url = VERIFIED_COMPLIANCE_DOCUMENTS["Nigeria"]
    print(f"Testing URL: {url}\n")

    # Step 1: raw fetch, see exactly what comes back
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(url)
            print(f"HTTP status: {response.status_code}")
            print(f"Content-Type: {response.headers.get('content-type')}")
            print(f"Content-Length: {len(response.content)} bytes\n")

            if response.status_code != 200:
                print("!!! Non-200 response. First 500 chars of body:")
                print(response.text[:500])
                return

            # Step 2: try PDF extraction directly, see if text comes out at all
            content_type = response.headers.get("content-type", "")
            if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
                reader = PdfReader(io.BytesIO(response.content))
                print(f"PDF pages detected: {len(reader.pages)}")
                full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
                print(f"Extracted text length: {len(full_text)} characters\n")
                print("First 500 characters of extracted text:")
                print(repr(full_text[:500]))
                print()
                print("Does extracted text contain 'breach' at all?", "breach" in full_text.lower())
                print("Does extracted text contain 'notification' at all?", "notification" in full_text.lower())
                print("Does extracted text contain 'cross-border' at all?", "cross-border" in full_text.lower())
            else:
                print("Response was not identified as a PDF.")

    except Exception as e:
        print(f"!!! Exception during raw fetch/parse: {type(e).__name__}: {e}")
        return

    print("\n--- Now testing the actual fetch_compliance_excerpt() function ---\n")

    result = await fetch_compliance_excerpt("Nigeria", "breach notification")
    print("fetch_compliance_excerpt('Nigeria', 'breach notification') ->")
    print(result)
    print()

    result2 = await fetch_compliance_excerpt("Nigeria", "cross-border data transfer")
    print("fetch_compliance_excerpt('Nigeria', 'cross-border data transfer') ->")
    print(result2)


if __name__ == "__main__":
    asyncio.run(main())

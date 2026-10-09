import os

pdf_body = """%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>
endobj
4 0 obj
<< /Length STREAM_LEN >>
stream
STREAM_DATA
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
6 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>
endobj
"""

text_lines = [
    ("OmniStream - User & Setup Instructions", True, 20),
    ("", False, 10),
    ("1. How to Share / Send the App", True, 14),
    ("- Do NOT send the uncompressed OmniStream.app file directly via email or chat.", False, 11),
    ("- Always send the OmniStream.zip archive to preserve executable permissions.", False, 11),
    ("", False, 10),
    ("2. Instructions for the Recipient (First-Time Setup)", True, 14),
    ("Step 1: Unzip the File", True, 12),
    ("  Double-click OmniStream.zip to extract the OmniStream app icon.", False, 11),
    ("", False, 6),
    ("Step 2: Bypass macOS Gatekeeper (Important!)", True, 12),
    ("  Because this app is self-packaged, macOS will show a security warning on first open.", False, 11),
    ("  To open it safely:", False, 11),
    ("  1. Right-click (or Control + Click) the OmniStream application icon.", False, 11),
    ("  2. Select 'Open' from the context menu.", False, 11),
    ("  3. When the popup window appears, click 'Open' again to confirm.", False, 11),
    ("  (You only need to do this step ONCE. Future launches work with double-click!)", False, 10),
    ("", False, 10),
    ("3. How to Use OmniStream", True, 14),
    ("1. Double-click OmniStream to open.", False, 11),
    ("2. Your default web browser will automatically open to: http://localhost:8888", False, 11),
    ("3. Paste any video link (YouTube, Vimeo, etc.) into the input box.", False, 11),
    ("4. Click 'Download Video'.", False, 11),
    ("5. Downloaded videos save automatically to your Mac's 'Downloads/OmniStream' folder!", False, 11)
]

stream_commands = []
y = 730
for text, is_bold, font_size in text_lines:
    if not text:
        y -= 10
        continue
    font_tag = "/F2" if is_bold else "/F1"
    escaped_text = text.replace("(", "\\(").replace(")", "\\)")
    cmd = f"BT {font_tag} {font_size} Tf 50 {y} Td ({escaped_text}) Tj ET"
    stream_commands.append(cmd)
    y -= (font_size + 6)

stream_data = "\n".join(stream_commands)
stream_len = len(stream_data.encode('latin1'))

pdf_body = pdf_body.replace("STREAM_LEN", str(stream_len)).replace("STREAM_DATA", stream_data)

objs = pdf_body.split("endobj\n")
offsets = []
current_offset = 0

for obj in objs[:-1]:
    offsets.append(current_offset)
    current_offset += len((obj + "endobj\n").encode('latin1'))

xref_start = current_offset
xref_entries = ["0000000000 65535 f \n"]
for off in offsets:
    xref_entries.append(f"{off:010d} 00000 n \n")

xref_table = f"xref\n0 {len(offsets)+1}\n" + "".join(xref_entries)
trailer = f"trailer\n<< /Size {len(offsets)+1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n"

final_pdf = pdf_body + xref_table + trailer

os.makedirs("/Users/chillsyeah/.gemini/antigravity/scratch/video-downloader-app/dist", exist_ok=True)
output_path = "/Users/chillsyeah/.gemini/antigravity/scratch/video-downloader-app/dist/OmniStream_Instructions.pdf"

with open(output_path, "wb") as f:
    f.write(final_pdf.encode('latin1'))

print("PDF generated successfully at:", output_path)

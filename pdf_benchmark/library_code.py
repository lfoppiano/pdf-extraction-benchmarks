import os
import subprocess
import tempfile
from io import BytesIO

import fitz as PyMuPDF
import pdfminer
import pdfplumber
import pypdf
import pypdfium2 as pdfium
from borb.pdf.pdf import PDF
from borb.toolkit.text.simple_text_extraction import SimpleTextExtraction
from pdfminer.high_level import extract_pages
from requests import ReadTimeout

from .text_extraction_post_processing import PDFIUM_ZERO_WIDTH_NO_BREAK_SPACE


def pymupdf_get_text(data: bytes) -> str:
    with PyMuPDF.open(stream=data, filetype="pdf") as doc:
        text = ""
        for page in doc:
            text += page.get_text() + "\n"
    return text


def pypdf_get_text(data: bytes) -> str:
    texts = []
    reader = pypdf.PdfReader(BytesIO(data))
    for page in reader.pages:
        texts.append(page.extract_text())
    text = "\n".join(texts)
    return text


def pdfium_new_line_after_hyphens(text):
    return text.replace(PDFIUM_ZERO_WIDTH_NO_BREAK_SPACE, PDFIUM_ZERO_WIDTH_NO_BREAK_SPACE + '\n')


def pdfium_get_text(data: bytes) -> str:
    texts = []
    pdf = pdfium.PdfDocument(data)

    for i in range(len(pdf)):
        page = pdf.get_page(i)
        textpage = page.get_textpage()
        texts.append(pdfium_new_line_after_hyphens(textpage.get_text_range()))
    text = "\n".join(texts)
    return text


def pdfium_image_extraction(data: bytes) -> list[tuple[str, bytes]]:
    images = []
    try:
        pdf = pdfium.PdfDocument(data)
        for i in range(len(pdf)):
            page = pdf.get_page(i)
            index = 1
            for obj in page.get_objects():
                if isinstance(obj, pdfium.PdfImage):
                    img = BytesIO()
                    obj.extract(img)
                    images.append((f"page-{i + 1}-image-{index}.jpg", img.getvalue()))
                    index += 1
    except Exception as exc:
        print(f"pdfium Image extraction failure: {exc}")
    return images


def pypdf_watermarking(watermark_data: bytes, data: bytes) -> bytes:
    watermark_pdf = pypdf.PdfReader(BytesIO(watermark_data))
    watermark_page = watermark_pdf.pages[0]
    reader = pypdf.PdfReader(BytesIO(data))
    writer = pypdf.PdfWriter()

    # Add the watermarks
    for page in reader.pages:
        page.merge_page(watermark_page)
        writer.add_page(page)

    # Compress the data
    for page in writer.pages:
        page.compress_content_streams()  # This is CPU intensive!

    # Write it back
    with BytesIO() as bytes_stream:
        writer.write(bytes_stream)
        bytes_stream.seek(0)
        return bytes_stream.read()


def pypdf_image_extraction(data: bytes) -> list[tuple[str, bytes]]:
    images = []
    try:
        reader = pypdf.PdfReader(BytesIO(data))
        for page in reader.pages:
            for image in page.images:
                images.append((image.name, image.data))
    except Exception as exc:
        print(f"pypdf Image extraction failure: {exc}")
    return images


def pymupdf_image_extraction(data: bytes) -> list[tuple[str, bytes]]:
    images = []
    with PyMuPDF.open(stream=data, filetype="pdf") as pdf_file:
        for page_index in range(len(pdf_file)):
            page = pdf_file[page_index]
            for image_index, img in enumerate(page.get_images(), start=1):
                xref = img[0]
                base_image = pdf_file.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]
                images.append(
                    (f"image{page_index + 1}_{image_index}.{image_ext}", image_bytes)
                )
    return images


def pymupdf_watermarking(watermark_data: bytes, data: bytes) -> bytes:
    pdf_file = PyMuPDF.open(stream=data, filetype="pdf")
    overlay = PyMuPDF.open(stream=watermark_data, filetype="pdf")
    for i in range(pdf_file.page_count):
        page = pdf_file.load_page(i)
        page_front = PyMuPDF.open()
        page_front.insert_pdf(overlay, from_page=i, to_page=i)
        page.show_pdf_page(
            page.rect,
            page_front,
            pno=0,
            keep_proportion=True,
            overlay=True,
            oc=0,
            rotate=0,
            clip=None,
        )
    return pdf_file.write()


def pdfminer_image_extraction(data: bytes) -> list[tuple[str, bytes]]:
    from PIL import Image

    def get_image(layout_object):
        if isinstance(layout_object, pdfminer.layout.LTImage):
            return layout_object
        if isinstance(layout_object, pdfminer.layout.LTContainer):
            for child in layout_object:
                return get_image(child)
        else:
            return None

    images = []
    try:
        pages = list(extract_pages(BytesIO(data)))
        for page in pages:
            ex_images = list(filter(bool, map(get_image, page)))
            for image in ex_images:
                image_pil = Image.frombytes(
                    "1", image.srcsize, image.stream.get_data(), "raw"
                )

                img_byte_arr = BytesIO()
                image_pil.save(img_byte_arr, format="PNG")
                img_byte_arr = img_byte_arr.getvalue()

                images.append((f"{image.name}.png", img_byte_arr))
    except Exception as exc:
        print(f"pdfminer Image extraction failure: {exc}")
    return images


def borb_get_text(data: bytes) -> str:
    text = ""
    try:
        ste = SimpleTextExtraction()
        PDF.loads(BytesIO(data), [ste])
        obj = ste.get_text()
        for page_index in range(len(obj)):
            text += obj[page_index]
    except Exception as exc:
        print(exc)
    return text


def pdfplubmer_get_text(data: bytes) -> str:
    text = ""
    with pdfplumber.open(BytesIO(data)) as pdf:
        for page in pdf.pages:
            text += page.extract_text()
            text += "\n"
    return text


def pdftotext_get_text(data: bytes) -> str:
    new_file, filename = tempfile.mkstemp()
    with open(filename, "wb") as fp:
        fp.write(data)
    pdf_to_text_path = "/usr/bin/pdftotext"
    if not os.path.exists(pdf_to_text_path):
        pdf_to_text_path = 'pdftotext'
    args = [pdf_to_text_path, "-enc", "UTF-8", filename, "-"]
    res = subprocess.run(args, capture_output=True)
    output = res.stdout.decode("utf-8")
    os.close(new_file)
    os.remove(filename)
    return output


def pdfalto_get_text(data: bytes) -> str:
    new_file, filename = tempfile.mkstemp()
    with open(filename, "wb") as fp:
        fp.write(data)
    pdf_to_text_path = os.environ["PDFALTO_EXECUTABLE"] if "PDFALTO_EXECUTABLE" in os.environ else None
    if not (pdf_to_text_path or os.path.exists(pdf_to_text_path)):
        print("To evaluate pdfalto, you need to create a .env file and place it at the root directory")
        pdf_to_text_path = 'pdfalto'
    args = [pdf_to_text_path, "-noImageInline", "-fullFontName", "-noImage", "-readingOrder", filename, "-"]

    res = subprocess.run(args, capture_output=True)
    output_xml = res.stdout.decode("utf-8")
    new_file_xml, filename_xml = tempfile.mkstemp()
    with open(filename_xml, "w") as fp:
        fp.write(output_xml)
    xml_to_txt_path = "/usr/bin/xsltproc"
    args = [xml_to_txt_path, "resources/pdfalto/alto2txt.xsl", filename_xml]
    res = subprocess.run(args, capture_output=True)
    output = res.stdout.decode("utf-8")
    os.close(new_file)
    os.close(new_file_xml)
    os.remove(filename)
    os.remove(filename_xml)
    return output

def pdfalto_get_images(data: bytes) -> list[tuple[str, bytes]]:
    images = []
    new_file, filename = tempfile.mkstemp()

    with open(filename, "wb") as fp:
        fp.write(data)
    pdf_to_text_path = os.environ["PDFALTO_EXECUTABLE"] if "PDFALTO_EXECUTABLE" in os.environ else None

    if not (pdf_to_text_path or os.path.exists(pdf_to_text_path)):
        print("To evaluate pdfalto, you need to create a .env file and place it at the root directory")
        pdf_to_text_path = 'pdfalto'

    output_directory = tempfile.TemporaryDirectory()
    args = [pdf_to_text_path, filename, output_directory.name]
    subprocess.run(args, capture_output=True)
    output_image_directory = f"{output_directory.name}_data"
    for idx, image in enumerate(os.listdir(output_image_directory)):
        with open(os.path.join(output_image_directory, image), "rb") as fp:
            images.append((image, fp.read()))

    os.close(new_file)
    os.remove(filename)
    return images
#
# def pdfalto_v05_get_text(data: bytes) -> str:
#     new_file, filename = tempfile.mkstemp()
#     with open(filename, "wb") as fp:
#         fp.write(data)
#     pdf_to_text_path = os.environ["PDFALTO_EXECUTABLE_v05"] if "PDFALTO_EXECUTABLE_v05" in os.environ else None
#     if not (pdf_to_text_path or os.path.exists(pdf_to_text_path)):
#         print("To evaluate pdfalto, you need to create a .env file and place it at the root directory")
#         pdf_to_text_path = 'pdfalto'
#     args = [pdf_to_text_path, "-noImageInline", "-fullFontName", "-noImage", "-readingOrder", filename, "-"]
#
#     res = subprocess.run(args, capture_output=True)
#     output_xml = res.stdout.decode("utf-8")
#     new_file_xml, filename_xml = tempfile.mkstemp()
#     with open(filename_xml, "w") as fp:
#         fp.write(output_xml)
#     xml_to_txt_path = "/usr/bin/xsltproc"
#     args = [xml_to_txt_path, "resources/pdfalto/alto2txt.xsl", filename_xml]
#     res = subprocess.run(args, capture_output=True)
#     output = res.stdout.decode("utf-8")
#     os.close(new_file)
#     os.close(new_file_xml)
#     os.remove(filename)
#     os.remove(filename_xml)
#     return output


def pdfrw_watermarking(watermark_data: bytes, data: bytes) -> bytes:
    from pdfrw import PageMerge, PdfReader, PdfWriter

    out_buffer = BytesIO()

    wmark = PageMerge().add(PdfReader(fdata=watermark_data).pages[0])[0]
    trailer = PdfReader(fdata=data)
    for page in trailer.pages:
        PageMerge(page).add(wmark, prepend=False).render()
    PdfWriter(out_buffer, trailer=trailer).write()

    out_buffer.seek(0)
    return out_buffer.read()


def tika_get_text(data: bytes) -> str:
    from tika import parser

    try:
        return parser.from_buffer(BytesIO(data), requestOptions={"timeout": (1, 100)})[
            "content"
        ]
    except ReadTimeout as ex:
        print("Tika timeout:", ex)
        return "[[[Tika text extraction failed!]]]"

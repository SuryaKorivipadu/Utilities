"""Read a PDF page by page into Markdown strings using pymupdf4llm."""

from pathlib import Path
import logging, re, os
from datetime import datetime
from typing import Union

import pymupdf4llm
import pymupdf


logger = logging.getLogger(__name__)

# Matches a Date of Service label at the beginning of a line, with optional
# Markdown bold markers. The named `date` group accepts ISO dates, slash-based
# dates, and month-name dates. It stops after the date, so trailing metadata
# such as `** | Type: OUTPATIENT VISIT` is not included in the result.
DATE_OF_SERVICE_PATTERN = re.compile(
	r"^\s*(?:\*\*)?Date of Service:\s*(?:\*\*)?\s*"
	r"(?P<date>"
	r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|"
	r"\d{1,2}/\d{1,2}/\d{4}|"
	r"(?:January|February|March|April|May|June|July|August|September|October|November|December|"
	r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+\d{1,2},\s*\d{4}"
	r")",
	re.IGNORECASE | re.MULTILINE,
)


def read_pdf_pages(pdf_path: Union[str, Path]) -> list[str]:
	"""Return one Markdown-formatted string for each PDF page."""
	try:
		logger.info("Opening PDF: %s", pdf_path)
		# page_chunks=True keeps the Markdown output separated by page.
		page_chunks = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True)
		pages = [chunk["text"] for chunk in page_chunks]
		for page_number, page_text in enumerate(pages, start=1):
			logger.debug("Extracted page %d (%d characters)", page_number, len(page_text))
	except (FileNotFoundError, OSError, RuntimeError):
		logger.exception("Unable to read PDF: %s", pdf_path)
		raise

	logger.info("Extracted text from %d page(s)", len(pages))
	return pages


def normalize_date(date_value: str) -> str:
	"""Convert supported date formats to YYYY-MM-DD."""
	clean_date = re.sub(r"\s+", " ", date_value.strip())
	clean_date = re.sub(r",\s*", ", ", clean_date)
	date_formats = (
		"%Y-%m-%d",
		"%Y/%m/%d",
		"%d/%m/%Y",
		"%m/%d/%Y",
		"%B %d, %Y",
		"%b %d, %Y",
	)
	for date_format in date_formats:
		try:
			return datetime.strptime(clean_date, date_format).strftime("%Y-%m-%d")
		except ValueError:
			continue
	logger.warning("Unsupported date format: %s", date_value)
	return ""


def extract_date_of_service(
	pages: list[str],
) -> tuple[list[dict[str, str | int]], list[dict[str, int]]]:
	"""Return page details and encounter page ranges grouped by date."""
	page_details = []
	previous_date_of_service = ""
	for page_number, page_text in enumerate(pages, start=1):
		match = DATE_OF_SERVICE_PATTERN.search(page_text)
		if match:
			previous_date_of_service = normalize_date(match.group("date"))
		date_of_service = previous_date_of_service
		page_details.append({"page_number": page_number, "date_of_service": date_of_service})
		logger.debug("Page %d date of service: %s", page_number, date_of_service or "not found")

	encounters = []
	current_date_of_service = ""
	current_start_page = 0
	for page_detail in page_details:
		page_number = int(page_detail["page_number"])
		date_of_service = str(page_detail["date_of_service"])
		if not date_of_service:
			continue

		if date_of_service != current_date_of_service:
			if current_date_of_service:
				encounters[-1]["end_page"] = page_number - 1
			current_date_of_service = date_of_service
			current_start_page = page_number
			encounters.append({
				"encounter_num": len(encounters) + 1,
				"start_page": current_start_page,
				"end_page": page_number,
			})
		else:
			encounters[-1]["end_page"] = page_number

	return page_details, encounters


def split_pdf_by_encounters(
	pdf_path: Union[str, Path],
	encounters: list[dict[str, int]],
	output_directory: Union[str, Path] = r"C:\Sury(A)\Code\Utilities\Data\Medical Coding\split_pdfs",
) -> list[Path]:
	"""Create one PDF per encounter using inclusive 1-based page ranges."""
	source_path = Path(pdf_path)
	output_path = Path(output_directory)
	output_folder_name = os.path.splitext(source_path.name)[0]
	output_path = os.path.join(output_path, output_folder_name)
	os.makedirs(output_path, exist_ok=True)
	created_files = []

	try:
		with pymupdf.open(source_path) as source_document:
			page_count = len(source_document)
			for encounter in encounters:
				encounter_number = encounter["encounter_num"]
				start_page = encounter["start_page"]
				end_page = encounter["end_page"]
				if not 1 <= start_page <= end_page <= page_count:
					raise ValueError(
						f"Invalid page range {start_page}-{end_page} for encounter "
						f"{encounter_number}; PDF has {page_count} page(s)."
					)

				encounter_document = pymupdf.open()
				try:
					# PyMuPDF uses zero-based page indexes; encounter pages are 1-based.
					encounter_document.insert_pdf(
						source_document,
						from_page=start_page - 1,
						to_page=end_page - 1,
					)
					output_file = os.path.join(output_path,f"{output_folder_name}_{start_page}-{end_page}.pdf",)
					encounter_document.save(output_file)
					created_files.append(Path(output_file))
					logger.info("Created encounter %d PDF: pages %d-%d -> %s",encounter_number,start_page,end_page,output_file)
				finally:
					encounter_document.close()
	except (FileNotFoundError, OSError, RuntimeError):
		logger.exception("Unable to split PDF: %s", source_path)
		raise

	return created_files


def main() -> None:
	"""Read a PDF path from user input and print its page text."""
	logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
	pdf_path = Path(input("Enter the path to the PDF file: ").strip())

	try:
		pages = read_pdf_pages(pdf_path)
	except (FileNotFoundError, OSError, RuntimeError) as error:
		print(f"Unable to read PDF: {error}")
		return

	page_details, encounters = extract_date_of_service(pages)
	print(encounters)
	split_pdf_by_encounters(pdf_path, encounters)
	logger.info("PDF splitting completed. Encounter PDFs saved in the output directory.")


if __name__ == "__main__":
	main()



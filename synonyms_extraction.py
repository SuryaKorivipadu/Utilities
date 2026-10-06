"""
Data Extraction Challenge: Synonyms for the Same Field  
In real‑world documents, the same concept often appears under different labels. For example, encounter date might be written as visit date, date of service, appointment date, or progress note date.

Instead of relying on the LLM to unify these automatically (which often fails), extract all possible synonyms separately into a JSON object. Then, use Python to parse the JSON and select whichever field had a value — ensuring that the correct date was captured regardless of the synonym used.
"""

dates = {
    "encounter_date": "2024-01-01",
    "visit_date": None,
    "appointment_date": None,
    "progress_note_date": None,
    "date_of_service": None
}
final_date = next((v for v in dates.values() if v), None)
print("Final Encounter Date:", final_date)

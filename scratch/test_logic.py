
import sys
from pathlib import Path

# Add project root to path
sys.path.append("/Users/ujjwalkalra14/MentorBot")

from config import STUDENTS
import re

def check_relevance(text):
    text_lower = text.lower()
    is_shraddha_tagged = "@eyeconicshraddha" in text_lower or "@shraddha" in text_lower
    
    mentioned_student_names = []
    for sid, info in STUDENTS.items():
        s_name = info["name"]
        first_name = s_name.split()[0].lower()
        full_name = s_name.lower()
        if full_name in text_lower or re.search(r'\b' + re.escape(first_name) + r'\b', text_lower):
            mentioned_student_names.append(s_name)

    return is_shraddha_tagged, mentioned_student_names

def match_students(student_names):
    target_ids = []
    student_names_low = [t.lower() for t in student_names]
    
    for chat_id, info in STUDENTS.items():
        s_name = info["name"].lower()
        s_parts = s_name.split()
        first_name = s_parts[0]
        
        match = False
        for target in student_names_low:
            if target == s_name or target == first_name or s_name in target or first_name in target:
                match = True
                break
            if any(p == target for p in s_parts):
                match = True
                break
        
        if match:
            target_ids.append(chat_id)
    return list(set(target_ids))

# Test cases
test_texts = [
    "@eyeconicshraddha Mitali Mittal check please",
    "@eyeconicsupport check Mitali",
    "Noel has completed the task",
    "Random message about nothing",
    "@eyeconicsupport Sahana Joshi convert back", # Not our student
    "@EyeconicShraddha Mittali Mittal" # AI might say Mittali
]

print("--- RELEVANCE TEST ---")
for t in test_texts:
    rel, students = check_relevance(t)
    print(f"Text: {t}")
    print(f"  Shraddha Tagged: {rel}, Students: {students}")

print("\n--- MATCHING TEST ---")
# Simulating AI output
ai_outputs = [
    ["Mitali Mittal"],
    ["Mitali"],
    ["Noel"],
    ["Mittali Mittal"], # AI typo or variation
    ["Shraddha Mittali Mittal"] # AI including tag
]

for names in ai_outputs:
    ids = match_students(names)
    print(f"Names: {names} -> IDs: {ids}")

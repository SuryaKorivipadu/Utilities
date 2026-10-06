from transformers import AutoModelForCausalLM, AutoTokenizer

model = AutoModelForCausalLM.from_pretrained("microsoft/Phi-3-mini-4k-instruct")
tokenizer = AutoTokenizer.from_pretrained("microsoft/Phi-3-mini-4k-instruct")

inputs = tokenizer("who is PM of india", return_tensors="pt")

outputs = model.generate(**inputs, max_new_tokens=100)

print(tokenizer.decode(outputs[0]))
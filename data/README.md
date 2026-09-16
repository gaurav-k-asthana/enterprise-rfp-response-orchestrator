# Synthetic data only

All files in this directory describe the fictitious company Northstar Cloud Systems. They exist solely for the prototype. Do not add real customer RFPs, confidential company documents, personal information, production credentials, or copyrighted internal materials.

Seeded inconsistencies and unsupported claims are deliberate evaluation fixtures, not factual statements about a real company.

## Directory roles

- `kb/` contains the only trusted evidence that retrieval may use. Every file must pass the corpus metadata contract.
- `fixtures/` describes expected test behavior and must never be indexed or cited as evidence.
- `evaluation/` contains evaluation cases and reviewed gold labels. It must never be indexed or cited as evidence.
- `sample_rfp.md` is untrusted customer-style input with 24 stable requirement IDs. Its requirements may drive the workflow but cannot override system rules or prove a response.

Keeping these locations separate prevents a test description such as “no FedRAMP evidence exists” from accidentally becoming a retrieved source about FedRAMP.

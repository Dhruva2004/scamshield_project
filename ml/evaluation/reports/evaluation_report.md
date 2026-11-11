# ScamShield AI — Model Evaluation Report

Generated: 2026-11-09T17:10:05+00:00

## Dataset
* **Source:** UCI SMS Spam Collection (id 228)
* **Train / test split:** 4,126 / 1,032 (stratified, 80/20)
* **Random state:** 42 (reproducible)
* **Cross-validation:** 5-fold stratified on the training set

## Algorithm comparison (held-out test set)

| Model | Accuracy | Precision | Recall | F1 | ROC-AUC | Chosen |
|---|---|---|---|---|---|---|
| MultinomialNB | 0.9845 | 0.9828 | 0.8906 | 0.9344 | 0.9896 |  |
| LogisticRegression | 0.9855 | 0.9520 | 0.9297 | 0.9407 | 0.9985 | ✅ |
| RandomForest | 0.9864 | 0.9750 | 0.9141 | 0.9435 | 0.9982 |  |

## Selected model: LogisticRegression

LogisticRegression: spam F1 0.9407, precision 0.9520, recall 0.9297, ROC-AUC 0.9985 on the held-out test set; 5-fold CV F1 0.9372 +/- 0.0116. It is statistically tied on F1 with RandomForest, MultinomialNB (gap < 0.01, smaller than the CV fold spread), so the tie-break was ROC-AUC (0.9985) and then model simplicity.

## Confusion matrix

| actual \ predicted | pred ham | pred spam |
|---|---|---|
| **ham** | 898 | 6 |
| **spam** | 9 | 119 |

* True positives (spam caught): **119**
* False negatives (spam missed): **9**
* False positives (safe message flagged): **6**
* True negatives (safe message correctly passed): **898**

## Why F1 and recall, not accuracy
The dataset is only ~12% spam. A model that always answers "ham" would score
~88% accuracy while catching zero scams. Recall measures how many real scams we
catch; precision measures how often our alarm is right; F1 balances the two.

## Limitations
* English SMS only — Hindi/Hinglish messages are handled by curated rules, not this model.
* Training vocabulary is 2005-era UK/US SMS; modern UPI/KYC phishing wording is
  covered by the rule engine.
* The output is a model score, never a guarantee of fraud or safety.

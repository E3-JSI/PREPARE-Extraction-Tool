from typing import Any, ClassVar, List, Sequence
from pydantic import BaseModel


class MultilingualClinicalConfig(BaseModel):
    """Static configuration for multilingual clinical extraction."""

    SUPPORTED_LANGS: ClassVar[Any] = {"en", "nl", "it", "sl", "de", "el"}

    NER_LABELS: ClassVar[Any] = {
        "en": ["measurement", "observation", "drug", "medication", "condition", "diagnosis"],
        "nl": [
            "measurement", "observation", "drug", "medication", "condition", "diagnosis",
            "meting", "observatie", "geneesmiddel", "medicatie", "aandoening", "diagnose",
        ],
        "it": [
            "measurement", "observation", "drug", "medication", "condition", "diagnosis",
            "misurazione", "osservazione", "farmaco", "medicazione", "condizione", "diagnosi",
        ],
        "sl": [
            "measurement", "observation", "drug", "medication", "condition", "diagnosis",
            "meritev", "opazovanje", "zdravilo", "medikacija", "stanje", "diagnoza",
        ],
        "de": [
            "measurement", "observation", "drug", "medication", "condition", "diagnosis",
            "messung", "beobachtung", "medikament", "arzneimittel", "zustand", "diagnose",
        ],
        "el": [
            "measurement", "observation", "drug", "medication", "condition", "diagnosis",
            "μέτρηση", "παρατήρηση", "φάρμακο", "αγωγή", "κατάσταση", "διάγνωση",
        ],
    }

    LABEL_NORMALIZATION: ClassVar[Any] = {
        "measurement": "MEASUREMENT",
        "observation": "OBSERVATION",
        "drug": "DRUG",
        "medication": "DRUG",
        "condition": "CONDITION",
        "diagnosis": "CONDITION",
        "meting": "MEASUREMENT",
        "observatie": "OBSERVATION",
        "geneesmiddel": "DRUG",
        "medicatie": "DRUG",
        "aandoening": "CONDITION",
        "diagnose": "CONDITION",
        "misurazione": "MEASUREMENT",
        "osservazione": "OBSERVATION",
        "farmaco": "DRUG",
        "medicazione": "DRUG",
        "condizione": "CONDITION",
        "diagnosi": "CONDITION",
        "meritev": "MEASUREMENT",
        "opazovanje": "OBSERVATION",
        "zdravilo": "DRUG",
        "medikacija": "DRUG",
        "stanje": "CONDITION",
        "diagnoza": "CONDITION",
        "messung": "MEASUREMENT",
        "beobachtung": "OBSERVATION",
        "medikament": "DRUG",
        "arzneimittel": "DRUG",
        "zustand": "CONDITION",
        "μέτρηση": "MEASUREMENT",
        "παρατήρηση": "OBSERVATION",
        "φάρμακο": "DRUG",
        "αγωγή": "DRUG",
        "κατάσταση": "CONDITION",
        "διάγνωση": "CONDITION",
    }

    LANGUAGE_HINTS: ClassVar[Any] = {
        "en": ["patient", "blood", "pressure", "suspected", "without", "daily", "take"],
        "nl": ["patiënt", "bloeddruk", "verdacht", "geen", "dagelijks", "ingenomen"],
        "it": ["paziente", "pressione", "sospett", "nessun", "giorno", "assunto"],
        "sl": ["bolnik", "krvni", "tlak", "sum", "brez", "dnevno", "jemal"],
        "de": ["patient", "blutdruck", "verdacht", "kein", "täglich", "eingenommen"],
        "el": ["ασθεν", "πίεση", "ύποπ", "χωρίς", "ημέρα", "έλαβε"],
    }

    UNITS: ClassVar[Any] = {
        "mmhg", "mg", "g", "kg", "ml", "μg", "mcg", "l", "iu", "bpm", "cm", "%", "°c",
        "mg/dl", "mmol/l", "puffs",
    }


    NEGATION_PHRASES: ClassVar[Any] = {
        "en": [
            "no signs of", "no evidence of", "did not take", "did not use", "did not receive",
            "was not taking", "not taking", "not taken", "without", "denies", "denied", "no", "not",
        ],
        "nl": [
            "geen tekenen van", "geen bewijs voor", "niet gebruikt", "niet ingenomen",
            "zonder", "ontkent", "geen", "niet",
        ],
        "it": [
            "nessun segno di", "nessuna evidenza di", "non ha assunto", "non assume",
            "non assunto", "senza", "nega", "nessun", "non",
        ],
        "sl": [
            "brez znakov", "brez dokazov za", "ni jemal", "ni jemala", "ne jemlje",
            "brez", "zanika", "ni", "ne",
        ],
        "de": [
            "keine anzeichen für", "kein hinweis auf", "nicht eingenommen", "nimmt nicht",
            "ohne", "verneint", "kein", "keine", "nicht",
        ],
        "el": [
            "χωρίς σημεία", "χωρίς ενδείξεις", "δεν έλαβε", "δεν λαμβάνει",
            "χωρίς", "δεν",
        ],
    }

    STATUS_PHRASES: ClassVar[Any] = {
        "en": ["suspected", "confirmed", "excluded", "known", "historical"],
        "nl": ["verdacht", "bevestigd", "uitgesloten", "bekend", "historisch"],
        "it": ["sospetta", "sospetto", "confermata", "confermato", "esclusa", "escluso", "nota", "noto"],
        "sl": ["sum na", "potrjeno", "izključeno", "znano", "anamnestično"],
        "de": ["verdacht auf", "verdacht", "bestätigt", "ausgeschlossen", "bekannt", "historisch"],
        "el": ["ύποπτη", "ύποπτο", "επιβεβαιωμένη", "επιβεβαιωμένο", "αποκλείστηκε", "γνωστή", "γνωστό"],
    }

    FREQUENCY_PHRASES: ClassVar[Any] = {
        "en": ["once daily", "twice daily", "three times daily", "daily", "weekly", "monthly", "as needed", "bid", "tid", "qid"],
        "nl": ["eenmaal daags", "tweemaal daags", "driemaal daags", "dagelijks", "wekelijks", "maandelijks", "zo nodig"],
        "it": ["una volta al giorno", "due volte al giorno", "tre volte al giorno", "giornalmente", "settimanalmente", "mensilmente"],
        "sl": ["enkrat dnevno", "dvakrat dnevno", "trikrat dnevno", "dnevno", "tedensko", "mesečno", "po potrebi"],
        "de": ["einmal täglich", "zweimal täglich", "dreimal täglich", "täglich", "wöchentlich", "monatlich", "bei bedarf"],
        "el": ["μία φορά την ημέρα", "δύο φορές την ημέρα", "τρεις φορές την ημέρα", "καθημερινά", "εβδομαδιαία", "μηνιαία"],
    }

    ROUTE_PHRASES: ClassVar[Any] = {
        "en": ["orally", "oral", "iv", "intravenous", "inhalation", "topical", "subcutaneous", "intramuscular"],
        "nl": ["oraal", "intraveneus", "inhalatie", "topisch", "subcutaan", "intramusculair"],
        "it": ["per via orale", "orale", "endovenosa", "inalazione", "topica", "sottocutanea", "intramuscolare"],
        "sl": ["peroralno", "oralno", "intravensko", "inhalacijsko", "lokalno", "subkutano", "intramuskularno"],
        "de": ["oral", "intravenös", "inhalation", "topisch", "subkutan", "intramuskulär"],
        "el": ["από το στόμα", "ενδοφλέβια", "εισπνοή", "τοπικά", "υποδόρια", "ενδομυϊκά"],
    }

    DURATION_STARTERS: ClassVar[Any] = {
        "en": {"for"},
        "nl": {"gedurende", "voor"},
        "it": {"per"},
        "sl": {"za", "skozi"},
        "de": {"für"},
        "el": {"για"},
    }

    DURATION_UNITS: ClassVar[Any] = {
        "en": {"day", "days", "week", "weeks", "month", "months", "hour", "hours"},
        "nl": {"dag", "dagen", "week", "weken", "maand", "maanden", "uur", "uren"},
        "it": {"giorno", "giorni", "settimana", "settimane", "mese", "mesi", "ora", "ore"},
        "sl": {"dan", "dni", "teden", "tedne", "tednov", "mesec", "mesece", "mesecev", "uro", "ur"},
        "de": {"tag", "tage", "tagen", "woche", "wochen", "monat", "monate", "monaten", "stunde", "stunden"},
        "el": {"ημέρα", "ημέρες", "εβδομάδα", "εβδομάδες", "μήνα", "μήνες", "ώρα", "ώρες"},
    }

    CONDITION_TERMS: ClassVar[Any] = {
        "en": {"asthma", "pneumonia", "diabetes", "hypertension", "infection", "fever", "copd", "bronchitis"},
        "nl": {"astma", "pneumonie", "diabetes", "hypertensie", "infectie", "koorts", "bronchitis"},
        "it": {"asma", "polmonite", "diabete", "ipertensione", "infezione", "febbre", "bronchite"},
        "sl": {"astma", "astme", "pljučnica", "pljučnico", "diabetes", "hipertenzija", "okužba", "vročina", "bronhitis"},
        "de": {"asthma", "pneumonie", "diabetes", "hypertonie", "infektion", "fieber", "bronchitis"},
        "el": {"άσθμα", "άσθματος", "πνευμονία", "διαβήτης", "υπέρταση", "λοίμωξη", "πυρετός", "βρογχίτιδα"},
    }

    DRUG_TERMS: ClassVar[Any] = {
        "en": {"ibuprofen", "paracetamol", "amoxicillin", "aspirin", "metformin", "azithromycin"},
        "nl": {"ibuprofen", "paracetamol", "amoxicilline", "aspirine", "metformine", "azitromycine"},
        "it": {"ibuprofene", "paracetamolo", "amoxicillina", "aspirina", "metformina", "azitromicina"},
        "sl": {"ibuprofen", "ibuprofena", "paracetamol", "amoksicilin", "aspirin", "metformin", "azitromicin"},
        "de": {"ibuprofen", "paracetamol", "amoxicillin", "aspirin", "metformin", "azithromycin"},
        "el": {"ιβουπροφαίνη", "ιβουπροφαίνης", "παρακεταμόλη", "αμοξικιλλίνη", "ασπιρίνη", "μετφορμίνη", "αζιθρομυκίνη"},
    }

    COMMON_MEASUREMENTS: ClassVar[Any] = {
        "en": ["systolic blood pressure", "blood pressure", "heart rate", "temperature", "glucose"],
        "nl": ["systolische bloeddruk", "bloeddruk", "hartslag", "temperatuur", "glucose"],
        "it": ["pressione arteriosa sistolica", "pressione arteriosa", "frequenza cardiaca", "temperatura", "glucosio"],
        "sl": ["sistolični krvni tlak", "krvni tlak", "srčni utrip", "temperatura", "glukoza"],
        "de": ["systolische blutdruck", "systolischer blutdruck", "blutdruck", "herzfrequenz", "temperatur", "glukose"],
        "el": ["συστολική αρτηριακή πίεση", "αρτηριακή πίεση", "καρδιακή συχνότητα", "θερμοκρασία", "γλυκόζη"],
    }

    @classmethod
    def normalize_phrase_list(cls, phrases: Sequence[str]) -> List[List[str]]:
        return [cls.normalize_text(p).split() for p in phrases]

    @staticmethod
    def normalize_text(text: str) -> str:
        return " ".join(text.casefold().strip().split())

    @classmethod
    def detect_language(cls, text: str) -> str:
        lowered = text.casefold()
        scores = {lang: sum(1 for hint in hints if hint in lowered) for lang, hints in cls.LANGUAGE_HINTS.items()}
        best_lang = max(scores, key=scores.get)
        return best_lang if scores[best_lang] > 0 else "en"
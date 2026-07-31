from __future__ import annotations

import datetime
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from sqlmodel import Session, delete, select

from app.library.sentence_segmenter import iter_sentence_spans
from app.models_db import Dataset, Record, SentenceSegment, SourceTerm, SourceTermLink


os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")

try:
    from gliner import GLiNER
except ImportError as exc:
    GLiNER = None
    GLINER_IMPORT_ERROR = exc
else:
    GLINER_IMPORT_ERROR = None

try:
    from transformers import pipeline as hf_pipeline
except ImportError:
    hf_pipeline = None


logger = logging.getLogger(__name__)


@dataclass
class Token:
    text: str
    norm: str
    start: int
    end: int


@dataclass
class SentenceSpan:
    start: int
    end: int
    token_start: int
    token_end: int


class MultilingualClinicalConfig:
    """Static configuration for multilingual clinical extraction."""

    SUPPORTED_LANGS = {"en", "nl", "it", "sl", "de", "el"}

    NER_LABELS = {
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

    LABEL_NORMALIZATION = {
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

    LANGUAGE_HINTS = {
        "en": ["patient", "blood", "pressure", "suspected", "without", "daily", "take"],
        "nl": ["patiënt", "bloeddruk", "verdacht", "geen", "dagelijks", "ingenomen"],
        "it": ["paziente", "pressione", "sospett", "nessun", "giorno", "assunto"],
        "sl": ["bolnik", "krvni", "tlak", "sum", "brez", "dnevno", "jemal"],
        "de": ["patient", "blutdruck", "verdacht", "kein", "täglich", "eingenommen"],
        "el": ["ασθεν", "πίεση", "ύποπ", "χωρίς", "ημέρα", "έλαβε"],
    }

    UNITS = {
        "mmhg", "mg", "g", "kg", "ml", "μg", "mcg", "l", "iu", "bpm", "cm", "%", "°c",
        "mg/dl", "mmol/l", "puffs",
    }


    NEGATION_PHRASES = {
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

    STATUS_PHRASES = {
        "en": ["suspected", "confirmed", "excluded", "known", "historical"],
        "nl": ["verdacht", "bevestigd", "uitgesloten", "bekend", "historisch"],
        "it": ["sospetta", "sospetto", "confermata", "confermato", "esclusa", "escluso", "nota", "noto"],
        "sl": ["sum na", "potrjeno", "izključeno", "znano", "anamnestično"],
        "de": ["verdacht auf", "verdacht", "bestätigt", "ausgeschlossen", "bekannt", "historisch"],
        "el": ["ύποπτη", "ύποπτο", "επιβεβαιωμένη", "επιβεβαιωμένο", "αποκλείστηκε", "γνωστή", "γνωστό"],
    }

    FREQUENCY_PHRASES = {
        "en": ["once daily", "twice daily", "three times daily", "daily", "weekly", "monthly", "as needed", "bid", "tid", "qid"],
        "nl": ["eenmaal daags", "tweemaal daags", "driemaal daags", "dagelijks", "wekelijks", "maandelijks", "zo nodig"],
        "it": ["una volta al giorno", "due volte al giorno", "tre volte al giorno", "giornalmente", "settimanalmente", "mensilmente"],
        "sl": ["enkrat dnevno", "dvakrat dnevno", "trikrat dnevno", "dnevno", "tedensko", "mesečno", "po potrebi"],
        "de": ["einmal täglich", "zweimal täglich", "dreimal täglich", "täglich", "wöchentlich", "monatlich", "bei bedarf"],
        "el": ["μία φορά την ημέρα", "δύο φορές την ημέρα", "τρεις φορές την ημέρα", "καθημερινά", "εβδομαδιαία", "μηνιαία"],
    }

    ROUTE_PHRASES = {
        "en": ["orally", "oral", "iv", "intravenous", "inhalation", "topical", "subcutaneous", "intramuscular"],
        "nl": ["oraal", "intraveneus", "inhalatie", "topisch", "subcutaan", "intramusculair"],
        "it": ["per via orale", "orale", "endovenosa", "inalazione", "topica", "sottocutanea", "intramuscolare"],
        "sl": ["peroralno", "oralno", "intravensko", "inhalacijsko", "lokalno", "subkutano", "intramuskularno"],
        "de": ["oral", "intravenös", "inhalation", "topisch", "subkutan", "intramuskulär"],
        "el": ["από το στόμα", "ενδοφλέβια", "εισπνοή", "τοπικά", "υποδόρια", "ενδομυϊκά"],
    }

    DURATION_STARTERS = {
        "en": {"for"},
        "nl": {"gedurende", "voor"},
        "it": {"per"},
        "sl": {"za", "skozi"},
        "de": {"für"},
        "el": {"για"},
    }

    DURATION_UNITS = {
        "en": {"day", "days", "week", "weeks", "month", "months", "hour", "hours"},
        "nl": {"dag", "dagen", "week", "weken", "maand", "maanden", "uur", "uren"},
        "it": {"giorno", "giorni", "settimana", "settimane", "mese", "mesi", "ora", "ore"},
        "sl": {"dan", "dni", "teden", "tedne", "tednov", "mesec", "mesece", "mesecev", "uro", "ur"},
        "de": {"tag", "tage", "tagen", "woche", "wochen", "monat", "monate", "monaten", "stunde", "stunden"},
        "el": {"ημέρα", "ημέρες", "εβδομάδα", "εβδομάδες", "μήνα", "μήνες", "ώρα", "ώρες"},
    }

    CONDITION_TERMS = {
        "en": {"asthma", "pneumonia", "diabetes", "hypertension", "infection", "fever", "copd", "bronchitis"},
        "nl": {"astma", "pneumonie", "diabetes", "hypertensie", "infectie", "koorts", "bronchitis"},
        "it": {"asma", "polmonite", "diabete", "ipertensione", "infezione", "febbre", "bronchite"},
        "sl": {"astma", "astme", "pljučnica", "pljučnico", "diabetes", "hipertenzija", "okužba", "vročina", "bronhitis"},
        "de": {"asthma", "pneumonie", "diabetes", "hypertonie", "infektion", "fieber", "bronchitis"},
        "el": {"άσθμα", "άσθματος", "πνευμονία", "διαβήτης", "υπέρταση", "λοίμωξη", "πυρετός", "βρογχίτιδα"},
    }

    DRUG_TERMS = {
        "en": {"ibuprofen", "paracetamol", "amoxicillin", "aspirin", "metformin", "azithromycin"},
        "nl": {"ibuprofen", "paracetamol", "amoxicilline", "aspirine", "metformine", "azitromycine"},
        "it": {"ibuprofene", "paracetamolo", "amoxicillina", "aspirina", "metformina", "azitromicina"},
        "sl": {"ibuprofen", "ibuprofena", "paracetamol", "amoksicilin", "aspirin", "metformin", "azitromicin"},
        "de": {"ibuprofen", "paracetamol", "amoxicillin", "aspirin", "metformin", "azithromycin"},
        "el": {"ιβουπροφαίνη", "ιβουπροφαίνης", "παρακεταμόλη", "αμοξικιλλίνη", "ασπιρίνη", "μετφορμίνη", "αζιθρομυκίνη"},
    }

    COMMON_MEASUREMENTS = {
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


class ClinicalTokenizer:

    TOKEN_PUNCT = set("/.-:,;()[]{}!?%")

    def tokenize(self, text: str) -> List[Token]:
        tokens: List[Token] = []
        i = 0
        while i < len(text):
            ch = text[i]
            if ch.isspace():
                i += 1
                continue

            start = i
            if ch.isalnum() or ch in {"μ", "°"}:
                i += 1
                while i < len(text) and (text[i].isalnum() or text[i] in {"μ", "°"}):
                    i += 1
            elif ch in self.TOKEN_PUNCT:
                i += 1
            else:
                i += 1

            raw = text[start:i]
            tokens.append(Token(text=raw, norm=raw.casefold(), start=start, end=i))
        return tokens

    def split_sentences(self, text: str, tokens: List[Token]) -> List[SentenceSpan]:
        if not tokens:
            return []

        sentence_spans: List[SentenceSpan] = []
        start_token = 0
        sent_start = tokens[0].start

        for idx, tok in enumerate(tokens):
            if tok.text in {".", "!", "?"}:
                sentence_spans.append(
                    SentenceSpan(
                        start=sent_start,
                        end=tok.end,
                        token_start=start_token,
                        token_end=idx + 1,
                    )
                )
                if idx + 1 < len(tokens):
                    start_token = idx + 1
                    sent_start = tokens[idx + 1].start

        if not sentence_spans or sentence_spans[-1].token_end < len(tokens):
            sentence_spans.append(
                SentenceSpan(
                    start=tokens[start_token].start,
                    end=tokens[-1].end,
                    token_start=start_token,
                    token_end=len(tokens),
                )
            )
        return sentence_spans


class EntityStore:
    """Stores entities and creates stable entity identifiers."""

    def __init__(self, text: str, entities: List[Dict[str, Any]]) -> None:
        self.text = text
        self.entities: List[Dict[str, Any]] = []
        self.next_id = 1

        for ent in sorted(entities, key=lambda e: (e["start"], e["end"], e["label"])):
            self.add_or_get(
                ent["start"],
                ent["end"],
                ent["label"],
                score=ent.get("score"),
                source=ent.get("source", "gliner"),
            )

    def _new_id(self) -> str:
        entity_id = f"T{self.next_id}"
        self.next_id += 1
        return entity_id

    def add_or_get(
        self,
        start: int,
        end: int,
        label: str,
        score: Optional[float] = None,
        source: str = "lexical",
    ) -> Dict[str, Any]:
        if start < 0 or end > len(self.text) or start >= end:
            raise ValueError(f"Invalid entity span: {start}:{end}")

        for ent in self.entities:
            if ent["start"] == start and ent["end"] == end and ent["label"] == label:
                if score is not None and ent.get("score") is None:
                    ent["score"] = score
                return ent

        entity: Dict[str, Any] = {
            "id": self._new_id(),
            "text": self.text[start:end],
            "label": label,
            "start": start,
            "end": end,
            "source": source,
        }
        if score is not None:
            entity["score"] = score
        self.entities.append(entity)
        self.entities.sort(key=lambda e: (e["start"], e["end"], e["label"]))
        return entity

    def find_overlapping(self, start: int, end: int, labels: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
        result = []
        for ent in self.entities:
            if labels is not None and ent["label"] not in labels:
                continue
            if not (ent["end"] <= start or ent["start"] >= end):
                result.append(ent)
        return result


class TokenLexicalEnricher:

    def __init__(self) -> None:
        self.tokenizer = ClinicalTokenizer()

    @staticmethod
    def _is_number_text(text: str) -> bool:
        value = text.replace(",", ".", 1)
        if value.count(".") > 1:
            return False
        parts = value.split(".")
        return bool(parts) and all(part.isdigit() for part in parts if part != "")

    @staticmethod
    def _valid_day_month_year(day: str, month: str, year: str) -> bool:
        if not (day.isdigit() and month.isdigit() and year.isdigit()):
            return False
        if not (1 <= len(day) <= 2 and 1 <= len(month) <= 2 and len(year) == 4):
            return False
        day_i, month_i = int(day), int(month)
        return 1 <= day_i <= 31 and 1 <= month_i <= 12

    @staticmethod
    def _valid_year_month_day(year: str, month: str, day: str) -> bool:
        if not (year.isdigit() and month.isdigit() and day.isdigit()):
            return False
        if not (len(year) == 4 and 1 <= len(month) <= 2 and 1 <= len(day) <= 2):
            return False
        day_i, month_i = int(day), int(month)
        return 1 <= day_i <= 31 and 1 <= month_i <= 12

    def _add_dates(self, store: EntityStore, tokens: List[Token]) -> None:
        idx = 0
        while idx + 4 < len(tokens):
            t0, t1, t2, t3, t4 = tokens[idx:idx + 5]
            sep_ok = t1.text in {"/", ".", "-"} and t3.text in {"/", ".", "-"}
            if not sep_ok:
                idx += 1
                continue

            if t1.text in {"/", "."} and self._valid_day_month_year(t0.text, t2.text, t4.text):
                store.add_or_get(t0.start, t4.end, "DATE", source="lexical")
                idx += 5
                continue

            if t1.text == "-" and self._valid_year_month_day(t0.text, t2.text, t4.text):
                store.add_or_get(t0.start, t4.end, "DATE", source="lexical")
                idx += 5
                continue

            idx += 1

    def _token_is_inside_label(self, token: Token, store: EntityStore, labels: Set[str]) -> bool:
        return bool(store.find_overlapping(token.start, token.end, labels))

    def _add_values_and_units(self, store: EntityStore, tokens: List[Token]) -> None:
        for tok in tokens:
            if self._token_is_inside_label(tok, store, {"DATE"}):
                continue
            if self._is_number_text(tok.text):
                store.add_or_get(tok.start, tok.end, "VALUE", source="lexical")

        idx = 0
        while idx < len(tokens):
            tok = tokens[idx]
            unit_start = tok.start
            unit_end = tok.end
            unit_norm = tok.norm

            if idx + 2 < len(tokens) and tokens[idx + 1].text == "/":
                combined_norm = f"{tokens[idx].norm}/{tokens[idx + 2].norm}"
                if combined_norm in MultilingualClinicalConfig.UNITS:
                    unit_norm = combined_norm
                    unit_end = tokens[idx + 2].end
                    idx += 3
                else:
                    idx += 1
            else:
                idx += 1

            if unit_norm in MultilingualClinicalConfig.UNITS:
                store.add_or_get(unit_start, unit_end, "UNIT", source="lexical")

    @staticmethod
    def _find_phrase_matches(norm_tokens: List[str], phrase_tokens: List[str], start: int, end: int) -> List[Tuple[int, int]]:
        matches: List[Tuple[int, int]] = []
        n = len(phrase_tokens)
        if n == 0:
            return matches
        for idx in range(start, end - n + 1):
            if norm_tokens[idx:idx + n] == phrase_tokens:
                matches.append((idx, idx + n))
        return matches

    def _add_phrase_entities(
        self,
        store: EntityStore,
        tokens: List[Token],
        sentence: SentenceSpan,
        phrases: Sequence[str],
        label: str,
    ) -> List[Dict[str, Any]]:
        norm_tokens = [tok.norm for tok in tokens]
        added: List[Dict[str, Any]] = []
        phrase_lists = MultilingualClinicalConfig.normalize_phrase_list(phrases)
        phrase_lists.sort(key=len, reverse=True)

        for phrase_tokens in phrase_lists:
            for start_idx, end_idx in self._find_phrase_matches(norm_tokens, phrase_tokens, sentence.token_start, sentence.token_end):
                ent = store.add_or_get(tokens[start_idx].start, tokens[end_idx - 1].end, label, source="lexical")
                added.append(ent)
        return added

    def _add_duration_entities(self, store: EntityStore, tokens: List[Token], sentence: SentenceSpan, language: str) -> None:
        starters = MultilingualClinicalConfig.DURATION_STARTERS.get(language, set())
        duration_units = MultilingualClinicalConfig.DURATION_UNITS.get(language, set())
        idx = sentence.token_start
        while idx + 2 < sentence.token_end:
            if tokens[idx].norm in starters and self._is_number_text(tokens[idx + 1].text) and tokens[idx + 2].norm in duration_units:
                store.add_or_get(tokens[idx].start, tokens[idx + 2].end, "DURATION", source="lexical")
                idx += 3
            else:
                idx += 1

    def _add_common_measurements(self, store: EntityStore, tokens: List[Token], sentence: SentenceSpan, language: str) -> None:
        phrases = MultilingualClinicalConfig.COMMON_MEASUREMENTS.get(language, [])
        self._add_phrase_entities(store, tokens, sentence, phrases, "MEASUREMENT")

    def _infer_object_after_cue(
        self,
        store: EntityStore,
        tokens: List[Token],
        sentence: SentenceSpan,
        cue_ent: Dict[str, Any],
        language: str,
        preferred_label: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Infer missing DRUG/CONDITION entity after a negation or status cue."""
        cue_end_token = None
        for idx in range(sentence.token_start, sentence.token_end):
            if tokens[idx].end == cue_ent["end"]:
                cue_end_token = idx + 1
                break
        if cue_end_token is None:
            return None

        condition_terms = MultilingualClinicalConfig.CONDITION_TERMS.get(language, set())
        drug_terms = MultilingualClinicalConfig.DRUG_TERMS.get(language, set())
        stop_words = {
            "on", "op", "il", "dne", "am", "στις", "στις", "de", "la", "der", "die", "das", "the",
            "was", "is", "je", "bil", "era", "war", "ήταν", "het", "patient", "patiënt", "paziente", "bolnik",
        }

        idx = cue_end_token
        while idx < sentence.token_end:
            tok = tokens[idx]
            if tok.text in {".", ",", ";", ":"}:
                break
            if self._token_is_inside_label(tok, store, {"DATE", "VALUE", "UNIT", "DURATION", "FREQUENCY", "ROUTE"}):
                idx += 1
                continue
            if tok.norm in stop_words:
                idx += 1
                continue

            label = preferred_label
            if label is None:
                if tok.norm in drug_terms:
                    label = "DRUG"
                elif tok.norm in condition_terms:
                    label = "CONDITION"

            if label is not None:
                # Extend one-token entities only when the following token is clearly part of the phrase.
                start_idx = idx
                end_idx = idx + 1
                return store.add_or_get(tokens[start_idx].start, tokens[end_idx - 1].end, label, source="cue_inference")

            idx += 1
        return None

    def enrich(
        self,
        text: str,
        initial_entities: List[Dict[str, Any]],
        language: str,
    ) -> Tuple[List[Dict[str, Any]], List[Token], List[SentenceSpan]]:
        tokens = self.tokenizer.tokenize(text)
        sentences = self.tokenizer.split_sentences(text, tokens)
        store = EntityStore(text, initial_entities)

        self._add_dates(store, tokens)
        self._add_values_and_units(store, tokens)

        for sentence in sentences:
            self._add_phrase_entities(
                store,
                tokens,
                sentence,
                MultilingualClinicalConfig.FREQUENCY_PHRASES.get(language, []),
                "FREQUENCY",
            )
            self._add_phrase_entities(
                store,
                tokens,
                sentence,
                MultilingualClinicalConfig.ROUTE_PHRASES.get(language, []),
                "ROUTE",
            )
            self._add_duration_entities(store, tokens, sentence, language)
            self._add_common_measurements(store, tokens, sentence, language)

            status_entities = self._add_phrase_entities(
                store,
                tokens,
                sentence,
                MultilingualClinicalConfig.STATUS_PHRASES.get(language, []),
                "STATUS",
            )
            negation_entities = self._add_phrase_entities(
                store,
                tokens,
                sentence,
                MultilingualClinicalConfig.NEGATION_PHRASES.get(language, []),
                "NEGATION",
            )

            for status in status_entities:
                self._infer_object_after_cue(store, tokens, sentence, status, language, preferred_label="CONDITION")
            for negation in negation_entities:
                self._infer_object_after_cue(store, tokens, sentence, negation, language)

        return store.entities, tokens, sentences


class EntityContextClassifier:
    """Classifies entity context with optional zero-shot model and rule-based fallback."""

    MODEL_LABELS = [
        "affirmed medical entity",
        "negated medical entity",
        "suspected medical entity",
        "historical medical entity",
        "planned medical entity",
    ]

    MODEL_LABEL_MAP = {
        "affirmed medical entity": "AFFIRMED",
        "negated medical entity": "NEGATED",
        "suspected medical entity": "UNCERTAIN",
        "historical medical entity": "HISTORICAL",
        "planned medical entity": "PLANNED",
    }

    def __init__(
        self,
        use_model: bool = False,
        model_name: str = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
        min_model_confidence: float = 0.62,
    ) -> None:
        self.use_model = use_model
        self.model_name = model_name
        self.min_model_confidence = min_model_confidence
        self.classifier = None

        if self.use_model:
            if hf_pipeline is None:
                raise ImportError("transformers is not installed. Install it or set use_context_classifier=False.")
            self.classifier = hf_pipeline("zero-shot-classification", model=model_name)

    @staticmethod
    def _window(text: str, entity: Dict[str, Any], size: int = 120) -> str:
        start = max(0, entity["start"] - size)
        end = min(len(text), entity["end"] + size)
        return text[start:end]

    @staticmethod
    def _has_any_phrase(text: str, phrases: Sequence[str]) -> bool:
        lowered = text.casefold()
        return any(phrase.casefold() in lowered for phrase in phrases)

    def _rule_based_context(self, text: str, entity: Dict[str, Any], language: str) -> Dict[str, Any]:
        context = self._window(text, entity)
        neg_phrases = MultilingualClinicalConfig.NEGATION_PHRASES.get(language, [])
        status_phrases = MultilingualClinicalConfig.STATUS_PHRASES.get(language, [])

        # These phrases often mean that the word "not/no" does not directly negate the entity.
        confusing_positive_phrases = [
            "not to stop", "not stop", "did not deny", "not excluded", "cannot be excluded",
            "niet stoppen", "niet ontkend", "non interrompere", "non esclusa", "ne preneha",
            "nicht absetzen", "nicht ausgeschlossen",
        ]

        if self._has_any_phrase(context, confusing_positive_phrases):
            return {"context_class": "AFFIRMED", "context_score": 0.70, "context_source": "rule_fallback"}

        if self._has_any_phrase(context, neg_phrases):
            return {"context_class": "NEGATED", "context_score": 0.80, "context_source": "rule_fallback"}
        if self._has_any_phrase(context, status_phrases):
            return {"context_class": "UNCERTAIN", "context_score": 0.75, "context_source": "rule_fallback"}
        return {"context_class": "AFFIRMED", "context_score": 0.60, "context_source": "rule_fallback"}

    def classify(self, text: str, entity: Dict[str, Any], language: str) -> Dict[str, Any]:
        fallback = self._rule_based_context(text, entity, language)
        if not self.use_model or self.classifier is None:
            return fallback

        context = self._window(text, entity)
        marked_context = context.replace(entity["text"], f"[ENTITY] {entity['text']} [/ENTITY]", 1)
        result = self.classifier(
            marked_context,
            candidate_labels=self.MODEL_LABELS,
            hypothesis_template="This example describes a {}.",
            multi_label=False,
        )

        best_label = result["labels"][0]
        best_score = float(result["scores"][0])
        mapped = self.MODEL_LABEL_MAP.get(best_label, "AFFIRMED")

        if best_score < self.min_model_confidence:
            fallback["context_model_label"] = best_label
            fallback["context_model_score"] = best_score
            fallback["context_source"] = "model_low_confidence_fallback"
            return fallback

        return {
            "context_class": mapped,
            "context_score": best_score,
            "context_model_label": best_label,
            "context_source": "zero_shot_model",
        }


class ClinicalRelationBuilder:
    """Builds deterministic relations using entity labels and context classes."""

    MEASUREMENT_LABELS = {"MEASUREMENT"}
    OBSERVATION_LABELS = {"OBSERVATION"}
    DRUG_LABELS = {"DRUG"}
    CONDITION_LABELS = {"CONDITION"}

    BLOCKED_IF_NEGATED = {
        "DRUG": {"HAS_DOSE", "HAS_UNIT", "HAS_DURATION", "HAS_FREQUENCY", "HAS_ROUTE"},
        "CONDITION": {"HAS_STATUS"},
        "MEASUREMENT": {"HAS_VALUE", "HAS_UNIT"},
        "OBSERVATION": {"HAS_VALUE"},
    }

    @staticmethod
    def _center(ent: Dict[str, Any]) -> float:
        return (ent["start"] + ent["end"]) / 2.0

    @staticmethod
    def _relation(rel_type: str, head: Dict[str, Any], tail: Dict[str, Any], source: str = "deterministic") -> Dict[str, Any]:
        return {"type": rel_type, "head": head["id"], "tail": tail["id"], "source": source}

    def _entities_in_sentence(self, entities: List[Dict[str, Any]], sentence: SentenceSpan) -> List[Dict[str, Any]]:
        return [e for e in entities if e["start"] >= sentence.start and e["end"] <= sentence.end]

    def _nearest(self, head: Dict[str, Any], candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not candidates:
            return None
        return min(candidates, key=lambda c: abs(self._center(head) - self._center(c)))

    def _nearest_right_or_any(self, head: Dict[str, Any], candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        right = [c for c in candidates if c["start"] >= head["end"]]
        return self._nearest(head, right or candidates)

    def _find_negation_tail(self, head: Dict[str, Any], negations: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        valid: List[Dict[str, Any]] = []
        for neg in negations:
            left_distance = head["start"] - neg["end"]
            right_distance = neg["start"] - head["end"]
            if 0 <= left_distance <= 70 or 0 <= right_distance <= 35:
                valid.append(neg)
        return self._nearest(head, valid)

    def _can_add_attribute(self, head: Dict[str, Any], rel_type: str) -> bool:
        if head.get("context_class") != "NEGATED":
            return True
        blocked = self.BLOCKED_IF_NEGATED.get(head["label"], set())
        return rel_type not in blocked

    def build(self, entities: List[Dict[str, Any]], sentences: List[SentenceSpan]) -> List[Dict[str, Any]]:
        relations: List[Dict[str, Any]] = []

        for sentence in sentences:
            sent_entities = self._entities_in_sentence(entities, sentence)
            dates = [e for e in sent_entities if e["label"] == "DATE"]
            values = [e for e in sent_entities if e["label"] == "VALUE"]
            units = [e for e in sent_entities if e["label"] == "UNIT"]
            durations = [e for e in sent_entities if e["label"] == "DURATION"]
            frequencies = [e for e in sent_entities if e["label"] == "FREQUENCY"]
            routes = [e for e in sent_entities if e["label"] == "ROUTE"]
            statuses = [e for e in sent_entities if e["label"] == "STATUS"]
            negations = [e for e in sent_entities if e["label"] == "NEGATION"]

            measurements = [e for e in sent_entities if e["label"] in self.MEASUREMENT_LABELS]
            observations = [e for e in sent_entities if e["label"] in self.OBSERVATION_LABELS]
            drugs = [e for e in sent_entities if e["label"] in self.DRUG_LABELS]
            conditions = [e for e in sent_entities if e["label"] in self.CONDITION_LABELS]

            positive_heads = measurements + observations + drugs + conditions
            for head in positive_heads:
                if head.get("context_class") == "NEGATED":
                    neg_tail = self._find_negation_tail(head, negations)
                    if neg_tail is not None:
                        relations.append(self._relation("NEGATED", head, neg_tail, source=head.get("context_source", "context_classifier")))
                elif head.get("context_class") == "UNCERTAIN" and head["label"] == "CONDITION":
                    status_tail = self._nearest(head, statuses)
                    if status_tail is not None:
                        relations.append(self._relation("HAS_STATUS", head, status_tail, source=head.get("context_source", "context_classifier")))

            # Measurements are connected to numeric value, unit and date unless they are negated.
            for ent in measurements:
                for rel_type, tail in [
                    ("HAS_VALUE", self._nearest_right_or_any(ent, values)),
                    ("HAS_UNIT", self._nearest_right_or_any(ent, units)),
                    ("HAS_DATE", self._nearest(ent, dates)),
                ]:
                    if tail is not None and self._can_add_attribute(ent, rel_type):
                        relations.append(self._relation(rel_type, ent, tail))

            for ent in observations:
                for rel_type, tail in [
                    ("HAS_VALUE", self._nearest_right_or_any(ent, values + statuses)),
                    ("HAS_DATE", self._nearest(ent, dates)),
                ]:
                    if tail is not None and self._can_add_attribute(ent, rel_type):
                        relations.append(self._relation(rel_type, ent, tail))

            for ent in drugs:
                for rel_type, tail in [
                    ("HAS_DOSE", self._nearest_right_or_any(ent, values)),
                    ("HAS_UNIT", self._nearest_right_or_any(ent, units)),
                    ("HAS_DURATION", self._nearest(ent, durations)),
                    ("HAS_FREQUENCY", self._nearest(ent, frequencies)),
                    ("HAS_ROUTE", self._nearest(ent, routes)),
                    ("HAS_DATE", self._nearest(ent, dates)),
                ]:
                    if tail is not None and self._can_add_attribute(ent, rel_type):
                        relations.append(self._relation(rel_type, ent, tail))

            for ent in conditions:
                for rel_type, tail in [
                    ("HAS_STATUS", self._nearest(ent, statuses)),
                    ("HAS_DATE", self._nearest(ent, dates)),
                ]:
                    if tail is not None and self._can_add_attribute(ent, rel_type):
                        relations.append(self._relation(rel_type, ent, tail))

        return self._deduplicate(relations)

    @staticmethod
    def _deduplicate(relations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        unique: List[Dict[str, Any]] = []
        for rel in relations:
            key = (rel["type"], rel["head"], rel["tail"])
            if key not in seen:
                seen.add(key)
                unique.append(rel)
        return unique


class ImprovedClinicalPipeline:
    def __init__(
        self,
        gliner_model_name: str = "urchade/gliner_multi-v2.1",
        use_context_classifier: bool = False,
        context_classifier_model: str = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
    ) -> None:
        if GLiNER is None:
            raise ImportError(
                "GLiNER is not installed. Install it with: pip install gliner"
            ) from GLINER_IMPORT_ERROR

        self.gliner = GLiNER.from_pretrained(gliner_model_name)
        self.enricher = TokenLexicalEnricher()
        self.context_classifier = EntityContextClassifier(
            use_model=use_context_classifier,
            model_name=context_classifier_model,
        )
        self.relation_builder = ClinicalRelationBuilder()

    @staticmethod
    def _normalize_label(
        label: str,
        extra_label_map: Optional[dict[str, str]] = None,
    ) -> str:
        normalized = MultilingualClinicalConfig.normalize_text(label)

        built_in_label = MultilingualClinicalConfig.LABEL_NORMALIZATION.get(
            normalized
        )
        if built_in_label:
            return built_in_label

        if extra_label_map and normalized in extra_label_map:
            return extra_label_map[normalized]

        return label.upper()

    def _labels_for_language(
        self,
        language: str,
        extra_labels: Optional[Sequence[str]] = None,
    ) -> List[str]:
        labels = list(
            MultilingualClinicalConfig.NER_LABELS.get(
                language,
                MultilingualClinicalConfig.NER_LABELS["en"],
            )
        )

        seen = {
            MultilingualClinicalConfig.normalize_text(label)
            for label in labels
        }

        for label in extra_labels or []:
            normalized = MultilingualClinicalConfig.normalize_text(label)

            if not normalized or normalized in seen:
                continue

            labels.append(label)
            seen.add(normalized)

        return labels

    def run_ner(
        self,
        text: str,
        language: str,
        threshold: float = 0.35,
        extra_label_map: Optional[dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        extra_label_map = extra_label_map or {}

        raw_entities = self.gliner.predict_entities(
            text,
            self._labels_for_language(
                language,
                extra_labels=list(extra_label_map.keys()),
            ),
            threshold=threshold,
            flat_ner=True,
        )

        entities: List[Dict[str, Any]] = []
        seen = set()

        for ent in raw_entities:
            label = self._normalize_label(
                ent["label"],
                extra_label_map=extra_label_map,
            )

            key = (ent["start"], ent["end"], label)
            if key in seen:
                continue

            seen.add(key)
            entities.append(
                {
                    "text": ent["text"],
                    "label": label,
                    "start": ent["start"],
                    "end": ent["end"],
                    "score": ent.get("score"),
                    "source": "gliner",
                }
            )
        return entities

    def run(
        self,
        text: str,
        language: Optional[str] = None,
        gliner_threshold: float = 0.35,
        extra_label_map: Optional[dict[str, str]] = None,
    ) -> Dict[str, Any]:
        if language is None:
            language = MultilingualClinicalConfig.detect_language(text)

        if language not in MultilingualClinicalConfig.SUPPORTED_LANGS:
            language = "en"

        ner_entities = self.run_ner(
            text,
            language=language,
            threshold=gliner_threshold,
            extra_label_map=extra_label_map,
        )
        enriched_entities, tokens, sentences = self.enricher.enrich(text, ner_entities, language)

        for ent in enriched_entities:
            if ent["label"] in {"DRUG", "CONDITION", "OBSERVATION", "MEASUREMENT"}:
                context = self.context_classifier.classify(text, ent, language)
                ent.update(context)

        relations = self.relation_builder.build(enriched_entities, sentences)
        return {
            "text": text,
            "language": language,
            "entities": enriched_entities,
            "relations": relations,
        }


_MULTI_SPACE = re.compile(r"\s+")
_TRAILING_PUNCT = re.compile(r"[,\.;:]+$")
_HAS_DIGIT = re.compile(r"\d")

_YEAR_ONLY = re.compile(r"^\s*(\d{4})\s*$")
_ISO_YMD = re.compile(r"^\s*(\d{4})[-/](\d{2})[-/](\d{2})\s*$")
_DMY_NUMERIC = re.compile(r"^\s*(\d{1,2})[\/\.-](\d{1,2})[\/\.-](\d{4})\s*$")


def _normalize_date_text(s: str) -> str:
    s = s.strip()
    s = _TRAILING_PUNCT.sub("", s)
    s = s.replace("\\", "/")
    s = _MULTI_SPACE.sub(" ", s)
    return s


def _safe_datetime(year: int, month: int, day: int) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime(year, month, day)
    except Exception:
        return None


def _visit_date_to_datetime(visit_date) -> Optional[datetime.datetime]:
    if visit_date is None:
        return None

    if isinstance(visit_date, datetime.datetime):
        return visit_date.replace(hour=0, minute=0, second=0, microsecond=0)

    if isinstance(visit_date, datetime.date):
        return datetime.datetime.combine(visit_date, datetime.time.min)

    return None


def _clamp_to_visit_date(
    parsed_dt: Optional[datetime.datetime],
    visit_date=None,
) -> Optional[datetime.datetime]:
    if parsed_dt is None:
        return None

    base_dt = _visit_date_to_datetime(visit_date)
    if base_dt is not None and parsed_dt > base_dt:
        return None

    return parsed_dt


def _try_parse_year_only(text: str, visit_date=None) -> Optional[datetime.datetime]:
    match = _YEAR_ONLY.match(text)
    if not match:
        return None

    year = int(match.group(1))
    parsed = _safe_datetime(year, 1, 1)
    return _clamp_to_visit_date(parsed, visit_date)


def _try_parse_iso_ymd(text: str, visit_date=None) -> Optional[datetime.datetime]:
    match = _ISO_YMD.match(text)
    if not match:
        return None

    year, month, day = match.groups()
    parsed = _safe_datetime(int(year), int(month), int(day))
    return _clamp_to_visit_date(parsed, visit_date)


def _try_parse_dmy_numeric(text: str, visit_date=None) -> Optional[datetime.datetime]:
    match = _DMY_NUMERIC.match(text)
    if not match:
        return None

    day, month, year = match.groups()
    parsed = _safe_datetime(int(year), int(month), int(day))
    return _clamp_to_visit_date(parsed, visit_date)


def _parse_date_value(
    value: Optional[str],
    visit_date=None,
) -> Optional[datetime.datetime]:
    if not value:
        return None

    text = _normalize_date_text(value)
    if not text:
        return None

    if _HAS_DIGIT.search(text) is None:
        return None

    parsed = _try_parse_year_only(text, visit_date)
    if parsed is not None:
        return parsed

    parsed = _try_parse_iso_ymd(text, visit_date)
    if parsed is not None:
        return parsed

    parsed = _try_parse_dmy_numeric(text, visit_date)
    if parsed is not None:
        return parsed

    return None


def _build_sentence_segments(record: Record) -> List[SentenceSegment]:
    spans = list(iter_sentence_spans(record.text or ""))
    segments: List[SentenceSegment] = []

    for index, (start, end) in enumerate(spans):
        segments.append(
            SentenceSegment(
                record_id=record.id,
                sequence_index=index,
                start_offset=start,
                end_offset=end,
            )
        )

    if not segments and record.text:
        segments.append(
            SentenceSegment(
                record_id=record.id,
                sequence_index=0,
                start_offset=0,
                end_offset=len(record.text),
            )
        )

    return segments


def bulk_insert_records_with_segments(
    db: Session,
    records: Sequence[Record],
) -> None:
    if not records:
        return

    db.bulk_save_objects(records, return_defaults=True)
    db.flush()

    segments: List[SentenceSegment] = []
    for record in records:
        if record.id is None:
            continue
        segments.extend(_build_sentence_segments(record))

    if segments:
        db.bulk_save_objects(segments, return_defaults=True)

    db.commit()


def regenerate_record_segments(db: Session, record: Record) -> None:
    db.exec(delete(SentenceSegment).where(SentenceSegment.record_id == record.id))

    segments = _build_sentence_segments(record)
    if segments:
        db.bulk_save_objects(segments, return_defaults=True)

    db.flush()


def _ensure_sentence_assignment(
    term: SourceTerm,
    segments: Sequence[SentenceSegment],
) -> None:
    if term.sentence_segment_id is not None:
        return

    if term.start_position is None:
        return

    end = term.end_position if term.end_position is not None else term.start_position
    for segment in segments:
        if segment.start_offset <= term.start_position and end <= segment.end_offset:
            term.sentence_segment_id = segment.id
            return


def _term_midpoint(
    term: SourceTerm,
    segment_lookup: dict[int | None, SentenceSegment],
) -> float:
    start = term.start_position
    end = term.end_position

    if start is None or end is None:
        segment = segment_lookup.get(term.sentence_segment_id)
        if segment:
            if start is None:
                start = segment.start_offset
            if end is None:
                end = segment.end_offset

    if start is None:
        start = 0
    if end is None:
        end = start

    return (start + end) / 2.0


def link_dates_for_record(
    db: Session,
    record: Record,
    dataset: Optional[Dataset] = None,
) -> None:
    dataset = dataset or record.dataset
    if dataset is None:
        dataset = db.get(Dataset, record.dataset_id)
        if dataset is None:
            return

    terms = db.exec(select(SourceTerm).where(SourceTerm.record_id == record.id)).all()
    if not terms:
        return

    segments = db.exec(
        select(SentenceSegment)
        .where(SentenceSegment.record_id == record.id)
        .order_by(SentenceSegment.sequence_index)
    ).all()

    if not segments and record.text:
        regenerate_record_segments(db, record)
        segments = db.exec(
            select(SentenceSegment)
            .where(SentenceSegment.record_id == record.id)
            .order_by(SentenceSegment.sequence_index)
        ).all()

    segment_lookup = {segment.id: segment for segment in segments}

    for term in terms:
        if not getattr(term, "manual_linked_visit_date", False):
            term.linked_date_term_id = None
            term.linked_visit_date = None
        _ensure_sentence_assignment(term, segments)

    grouped = defaultdict(list)
    for term in terms:
        grouped[term.sentence_segment_id].append(term)

    date_label = dataset.date_label
    fallback_date = _visit_date_to_datetime(record.visit_date)

    for _, segment_terms in grouped.items():
        if not date_label:
            for term in segment_terms:
                if not getattr(term, "manual_linked_visit_date", False):
                    term.linked_visit_date = fallback_date
            continue

        date_terms: List[Tuple[SourceTerm, Optional[datetime.datetime]]] = []
        for term in segment_terms:
            if term.label == date_label:
                parsed = _parse_date_value(term.value, fallback_date)

                if not getattr(term, "manual_linked_visit_date", False):
                    term.linked_visit_date = parsed

                date_terms.append((term, parsed))

        non_date_terms = [term for term in segment_terms if term.label != date_label]
        valid_dates = [(term, dt) for term, dt in date_terms if dt is not None]

        if len(valid_dates) == 1:
            date_term, parsed_dt = valid_dates[0]
            for entity in non_date_terms:
                if not getattr(entity, "manual_linked_visit_date", False):
                    entity.linked_date_term_id = date_term.id
                    entity.linked_visit_date = parsed_dt

        elif len(valid_dates) > 1:
            date_midpoints = {
                date_term.id: _term_midpoint(date_term, segment_lookup)
                for date_term, _ in valid_dates
            }

            for entity in non_date_terms:
                entity_mid = _term_midpoint(entity, segment_lookup)
                closest_term_id = None
                closest_dt = None
                closest_distance = None

                for date_term, parsed_dt in valid_dates:
                    midpoint = date_midpoints[date_term.id]
                    distance = abs(entity_mid - midpoint)

                    if closest_distance is None or distance < closest_distance:
                        closest_distance = distance
                        closest_term_id = date_term.id
                        closest_dt = parsed_dt

                if not getattr(entity, "manual_linked_visit_date", False):
                    entity.linked_date_term_id = closest_term_id
                    entity.linked_visit_date = closest_dt

        else:
            for entity in non_date_terms:
                if not getattr(entity, "manual_linked_visit_date", False):
                    entity.linked_visit_date = fallback_date

    db.flush()


@lru_cache(maxsize=1)
def get_clinical_pipeline() -> ImprovedClinicalPipeline:
    use_context_model = os.getenv("CLINICAL_USE_CONTEXT_MODEL", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    return ImprovedClinicalPipeline(
        gliner_model_name=os.getenv(
            "CLINICAL_GLINER_MODEL",
            "urchade/gliner_multi-v2.1",
        ),
        use_context_classifier=use_context_model,
        context_classifier_model=os.getenv(
            "CLINICAL_CONTEXT_MODEL",
            "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
        ),
    )


def _model_field_names(model_class: type) -> set[str]:
    """Return SQLModel/Pydantic field names without depending on its version."""
    fields = getattr(model_class, "model_fields", None)
    if fields is None:
        fields = getattr(model_class, "__fields__", {})
    return set(fields.keys())


def _normalized_label(label: Optional[str]) -> str:
    return (label or "").strip().casefold()


_RULE_BASED_LABELS = {
    "date",
    "value",
    "unit",
    "duration",
    "frequency",
    "route",
    "status",
    "negation",
}


def _label_prompt(label: str) -> str:
    """Convert dataset labels into GLiNER-friendly prompts."""
    return " ".join(
        str(label)
        .replace("_", " ")
        .replace("-", " ")
        .strip()
        .casefold()
        .split()
    )


def _collect_labels_from_config(value: Any) -> List[str]:
    """Extract labels from different possible dataset config shapes."""
    labels: List[str] = []

    if value is None:
        return labels

    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            labels.append(stripped)
        return labels

    if isinstance(value, dict):
        for key in (
            "label",
            "name",
            "value",
            "from_label",
            "to_label",
        ):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                labels.append(item.strip())

        for key in (
            "labels",
            "entity_labels",
            "label_names",
            "items",
            "options",
        ):
            labels.extend(_collect_labels_from_config(value.get(key)))

        return labels

    if isinstance(value, (list, tuple, set)):
        for item in value:
            labels.extend(_collect_labels_from_config(item))
        return labels

    return labels


def _dataset_gliner_label_map(dataset: Dataset) -> dict[str, str]:
    label_map: dict[str, str] = {}

    def add_label(label: Optional[str]) -> None:
        if not label:
            return

        storage_label = str(label).strip()
        if not storage_label:
            return

        normalized = _normalized_label(storage_label)
        if normalized in _RULE_BASED_LABELS:
            return

        prompt = _label_prompt(storage_label)
        if not prompt:
            return

        label_map.setdefault(prompt, storage_label)

    for relation in getattr(dataset, "label_relations", None) or []:
        if isinstance(relation, dict):
            add_label(relation.get("from_label"))
            add_label(relation.get("to_label"))

    for attr_name in (
        "labels",
        "entity_labels",
        "label_names",
        "label_config",
        "annotation_labels",
        "source_labels",
    ):
        for label in _collect_labels_from_config(getattr(dataset, attr_name, None)):
            add_label(label)

    return label_map


def _storage_label(entity_label: str, dataset: Dataset) -> str:
    """Keep the configured date label compatible with the existing frontend."""
    if entity_label == "DATE" and getattr(dataset, "date_label", None):
        return dataset.date_label
    return entity_label


def _get_or_create_pipeline_terms(
    db: Session,
    record: Record,
    dataset: Dataset,
    entities: Sequence[Dict[str, Any]],
    segments: Sequence[SentenceSegment],
) -> dict[str, SourceTerm]:
    """Merge pipeline entities into the existing SourceTerm table."""
    existing_terms = db.exec(
        select(SourceTerm)
        .where(SourceTerm.record_id == record.id)
        .order_by(SourceTerm.start_position)
    ).all()

    by_exact_span: dict[tuple[int, int, str], SourceTerm] = {}
    for term in existing_terms:
        if term.start_position is None or term.end_position is None:
            continue
        by_exact_span[
            (
                term.start_position,
                term.end_position,
                _normalized_label(term.label),
            )
        ] = term

    source_term_fields = _model_field_names(SourceTerm)
    entity_map: dict[str, SourceTerm] = {}
    new_terms: List[SourceTerm] = []

    for entity in entities:
        pipeline_id = entity.get("id")
        start = entity.get("start")
        end = entity.get("end")
        raw_label = entity.get("label")
        value = entity.get("text")

        if (
            not pipeline_id
            or start is None
            or end is None
            or not raw_label
            or not value
        ):
            continue

        label = _storage_label(str(raw_label), dataset)
        key = (int(start), int(end), _normalized_label(label))
        source_term = by_exact_span.get(key)

        if source_term is None:
            kwargs: Dict[str, Any] = {
                "record_id": record.id,
                "value": value,
                "label": label,
                "start_position": int(start),
                "end_position": int(end),
            }

            optional_values = {
                "source": entity.get("source"),
                "score": entity.get("score"),
                "context_class": entity.get("context_class"),
                "context_score": entity.get("context_score"),
                "context_source": entity.get("context_source"),
            }
            for field_name, field_value in optional_values.items():
                if field_name in source_term_fields and field_value is not None:
                    kwargs[field_name] = field_value

            source_term = SourceTerm(**kwargs)
            _ensure_sentence_assignment(source_term, segments)
            new_terms.append(source_term)
            by_exact_span[key] = source_term
        else:
            for field_name in (
                "source",
                "score",
                "context_class",
                "context_score",
                "context_source",
            ):
                if field_name not in source_term_fields:
                    continue
                field_value = entity.get(field_name)
                if field_value is not None:
                    setattr(source_term, field_name, field_value)
            _ensure_sentence_assignment(source_term, segments)

        entity_map[str(pipeline_id)] = source_term

    if new_terms:
        db.add_all(new_terms)

    db.flush()
    return entity_map


def _save_pipeline_relations(
    db: Session,
    dataset: Dataset,
    entity_map: dict[str, SourceTerm],
    relations: Sequence[Dict[str, Any]],
) -> None:
    mapped_term_ids = [
        term.id
        for term in entity_map.values()
        if term.id is not None
    ]
    if not mapped_term_ids:
        return

    existing = {
        (link.from_term_id, link.to_term_id)
        for link in db.exec(
            select(SourceTermLink).where(
                SourceTermLink.from_term_id.in_(mapped_term_ids)
            )
        ).all()
    }

    link_fields = _model_field_names(SourceTermLink)
    new_links: List[SourceTermLink] = []

    for relation in relations:
        head = entity_map.get(str(relation.get("head")))
        tail = entity_map.get(str(relation.get("tail")))

        if (
            head is None
            or tail is None
            or head.id is None
            or tail.id is None
            or head.id == tail.id
        ):
            continue

        key = (head.id, tail.id)
        if key in existing:
            continue

        kwargs: Dict[str, Any] = {
            "from_term_id": head.id,
            "to_term_id": tail.id,
            "dataset_id": dataset.id,
        }

        # These fields are used only when they already exist in the model.
        # Therefore older API schemas and the frontend remain compatible.
        if "relation_type" in link_fields and relation.get("type") is not None:
            kwargs["relation_type"] = relation.get("type")
        elif "type" in link_fields and relation.get("type") is not None:
            kwargs["type"] = relation.get("type")

        if "relation_source" in link_fields and relation.get("source") is not None:
            kwargs["relation_source"] = relation.get("source")
        elif "source" in link_fields and relation.get("source") is not None:
            kwargs["source"] = relation.get("source")

        new_links.append(SourceTermLink(**kwargs))
        existing.add(key)

    if new_links:
        db.add_all(new_links)
        db.flush()


def _nearest_source_term(
    head: SourceTerm,
    candidates: Sequence[SourceTerm],
    segment_lookup: dict[int | None, SentenceSegment],
) -> Optional[SourceTerm]:
    if not candidates:
        return None

    head_end = head.end_position
    if head_end is None:
        head_end = head.start_position

    right_candidates = [
        candidate
        for candidate in candidates
        if candidate.start_position is not None
        and head_end is not None
        and candidate.start_position >= head_end
    ]
    candidate_pool = right_candidates or list(candidates)
    head_midpoint = _term_midpoint(head, segment_lookup)

    return min(
        candidate_pool,
        key=lambda candidate: abs(
            _term_midpoint(candidate, segment_lookup) - head_midpoint
        ),
    )


def _link_configured_dataset_relations(
    db: Session,
    record: Record,
    dataset: Dataset,
) -> None:
    if not dataset.label_relations:
        return

    relation_map: dict[str, set[str]] = {}
    for relation in dataset.label_relations:
        from_label = relation.get("from_label")
        to_label = relation.get("to_label")
        if from_label and to_label:
            relation_map.setdefault(
                _normalized_label(from_label),
                set(),
            ).add(_normalized_label(to_label))

    if not relation_map:
        return

    terms = db.exec(
        select(SourceTerm)
        .where(SourceTerm.record_id == record.id)
        .order_by(SourceTerm.start_position)
    ).all()
    if len(terms) < 2:
        return

    segments = db.exec(
        select(SentenceSegment)
        .where(SentenceSegment.record_id == record.id)
        .order_by(SentenceSegment.sequence_index)
    ).all()
    if not segments and record.text:
        regenerate_record_segments(db, record)
        segments = db.exec(
            select(SentenceSegment)
            .where(SentenceSegment.record_id == record.id)
            .order_by(SentenceSegment.sequence_index)
        ).all()

    for term in terms:
        _ensure_sentence_assignment(term, segments)
    db.flush()

    segment_lookup = {segment.id: segment for segment in segments}
    terms_by_sentence: dict[int | None, list[SourceTerm]] = defaultdict(list)
    for term in terms:
        terms_by_sentence[term.sentence_segment_id].append(term)

    term_ids = [term.id for term in terms if term.id is not None]
    if not term_ids:
        return

    existing = {
        (link.from_term_id, link.to_term_id)
        for link in db.exec(
            select(SourceTermLink).where(
                SourceTermLink.from_term_id.in_(term_ids)
            )
        ).all()
    }

    new_links: List[SourceTermLink] = []
    for head in terms:
        if head.id is None:
            continue

        target_labels = relation_map.get(_normalized_label(head.label))
        if not target_labels:
            continue

        sentence_terms = terms_by_sentence.get(head.sentence_segment_id, [])
        for target_label in target_labels:
            candidates = [
                candidate
                for candidate in sentence_terms
                if candidate.id is not None
                and candidate.id != head.id
                and _normalized_label(candidate.label) == target_label
            ]
            target = _nearest_source_term(head, candidates, segment_lookup)
            if target is None or target.id is None:
                continue

            key = (head.id, target.id)
            if key in existing:
                continue

            existing.add(key)
            new_links.append(
                SourceTermLink(
                    from_term_id=head.id,
                    to_term_id=target.id,
                    dataset_id=dataset.id,
                )
            )

    if new_links:
        db.add_all(new_links)
        db.flush()


def auto_link_entities_for_record(
    db: Session,
    record: Record,
    dataset: Dataset,
) -> None:
    """
    Processing order:
      1. GLiNER entity extraction.
      2. Token-based DATE/VALUE/UNIT/FREQUENCY/ROUTE/DURATION enrichment.
      3. NEGATION and STATUS cue extraction.
      4. Rule-based or optional zero-shot context classification.
      5. Deterministic clinical relation building.
      6. Existing visit-date linking and dataset relation fallback.
    """
    if record.id is None:
        return

    text = record.text or ""
    if not text.strip():
        return

    segments = db.exec(
        select(SentenceSegment)
        .where(SentenceSegment.record_id == record.id)
        .order_by(SentenceSegment.sequence_index)
    ).all()
    if not segments:
        regenerate_record_segments(db, record)
        segments = db.exec(
            select(SentenceSegment)
            .where(SentenceSegment.record_id == record.id)
            .order_by(SentenceSegment.sequence_index)
        ).all()

    try:
        pipeline = get_clinical_pipeline()
        extra_label_map = _dataset_gliner_label_map(dataset)
        result = pipeline.run(
            text=text,
            language=None,
            gliner_threshold=float(
                os.getenv("CLINICAL_GLINER_THRESHOLD", "0.35")
            ),
            extra_label_map=extra_label_map,
        )

        entity_map = _get_or_create_pipeline_terms(
            db=db,
            record=record,
            dataset=dataset,
            entities=result.get("entities", []),
            segments=segments,
        )
        _save_pipeline_relations(
            db=db,
            dataset=dataset,
            entity_map=entity_map,
            relations=result.get("relations", []),
        )
    except Exception:
        logger.exception(
            "The clinical extraction pipeline failed for record_id=%s",
            record.id,
        )
        strict = os.getenv("CLINICAL_PIPELINE_STRICT", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if strict:
            raise

    link_dates_for_record(db=db, record=record, dataset=dataset)

    _link_configured_dataset_relations(db=db, record=record, dataset=dataset)


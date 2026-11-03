from __future__ import annotations

import datetime
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.interfaces import Token, SentenceSpan
from app.schemas import MultilingualClinicalConfig
from app.library.sentence_segmenter import iter_sentence_spans

try:
    from transformers import pipeline as hf_pipeline
except ImportError:
    hf_pipeline = None


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
        """Use the SAME sentence boundaries as persisted SentenceSegment rows.

        The shared segmenter splits at punctuation followed by whitespace,
        never at the periods inside 37.5 or 12.05.2020. Each token retains
        its character offsets in the original record text.
        """
        if not tokens:
            return []

        result: List[SentenceSpan] = []
        token_idx = 0
        for start, end in iter_sentence_spans(text):
            while token_idx < len(tokens) and tokens[token_idx].end <= start:
                token_idx += 1
            first_idx = token_idx
            while token_idx < len(tokens) and tokens[token_idx].end <= end:
                token_idx += 1
            if token_idx > first_idx:
                result.append(
                    SentenceSpan(
                        start=start,
                        end=end,
                        token_start=first_idx,
                        token_end=token_idx,
                    )
                )
        return result


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
                clinical_type=ent.get("clinical_type"),
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
        clinical_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        if start < 0 or end > len(self.text) or start >= end:
            raise ValueError(f"Invalid entity span: {start}:{end}")

        for ent in self.entities:
            if ent["start"] == start and ent["end"] == end and ent["label"] == label:
                if score is not None and ent.get("score") is None:
                    ent["score"] = score
                if clinical_type and not ent.get("clinical_type"):
                    ent["clinical_type"] = clinical_type
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
        if clinical_type:
            entity["clinical_type"] = clinical_type
        elif label in {"DATE", "VALUE", "UNIT", "DURATION", "FREQUENCY", "ROUTE", "STATUS", "NEGATION", "MEASUREMENT", "DRUG", "CONDITION", "OBSERVATION"}:
            entity["clinical_type"] = label
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
        return re.fullmatch(r"\d+(?:[.,]\d+)?", text) is not None

    @staticmethod
    def _valid_day_month_year(day: str, month: str, year: str) -> bool:
        if not (day.isdigit() and month.isdigit() and year.isdigit()):
            return False
        if not (1 <= len(day) <= 2 and 1 <= len(month) <= 2 and len(year) == 4):
            return False
        try:
            datetime.date(int(year), int(month), int(day))
        except ValueError:
            return False
        return True

    @staticmethod
    def _valid_year_month_day(year: str, month: str, day: str) -> bool:
        if not (year.isdigit() and month.isdigit() and day.isdigit()):
            return False
        if not (len(year) == 4 and 1 <= len(month) <= 2 and 1 <= len(day) <= 2):
            return False
        try:
            datetime.date(int(year), int(month), int(day))
        except ValueError:
            return False
        return True

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
        idx = 0
        while idx < len(tokens):
            tok = tokens[idx]
            if self._token_is_inside_label(tok, store, {"DATE"}):
                idx += 1
                continue

            # Tokenizer keeps punctuation separate. Recombine adjacent digit,
            # separator, digit triples to retain the entire numeric value.
            if (
                idx + 2 < len(tokens)
                and tok.text.isdigit()
                and tokens[idx + 1].text in {".", ","}
                and tokens[idx + 2].text.isdigit()
                and tok.end == tokens[idx + 1].start
                and tokens[idx + 1].end == tokens[idx + 2].start
                and not any(self._token_is_inside_label(t, store, {"DATE"}) for t in tokens[idx:idx + 3])
            ):
                store.add_or_get(tok.start, tokens[idx + 2].end, "VALUE", source="lexical")
                idx += 3
                continue
            if self._is_number_text(tok.text):
                store.add_or_get(tok.start, tok.end, "VALUE", source="lexical")
            idx += 1

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
    def _phrase_match(text: str, phrase: str) -> bool:
        """Match a standalone Unicode word/phrase (never 'ni' inside 'bolnik')."""
        words = phrase.casefold().split()
        if not words:
            return False
        pattern = r"(?<!\w)" + r"\s+".join(map(re.escape, words)) + r"(?!\w)"
        return re.search(pattern, text.casefold()) is not None

    @classmethod
    def _has_any_phrase(cls, text: str, phrases: Sequence[str]) -> bool:
        return any(cls._phrase_match(text, phrase) for phrase in phrases)

    @staticmethod
    def _local_clause(text: str, entity: Dict[str, Any]) -> str:
        """Find a nearby cue within the entity's sentence and clause.

        A negation from an unrelated sentence or a clause after a comma must
        not negate this entity. Limit scope to eight tokens before and four
        after the entity, for a conservative rule-based fallback.
        """
        tokenizer = ClinicalTokenizer()
        tokens = tokenizer.tokenize(text)
        if not tokens:
            return ""
        sentences = tokenizer.split_sentences(text, tokens)
        sentence = next(
            (s for s in sentences if s.start <= entity["start"] and entity["end"] <= s.end),
            None,
        )
        if sentence is None:
            return ""
        matching_indices = [
            idx for idx in range(sentence.token_start, sentence.token_end)
            if tokens[idx].start < entity["end"] and tokens[idx].end > entity["start"]
        ]
        if not matching_indices:
            return ""
        first, last = matching_indices[0], matching_indices[-1]
        left, right = max(sentence.token_start, first - 8), min(sentence.token_end, last + 5)
        contrast_words = {"but", "however", "ampak", "vendar", "maar", "aber", "ma", "αλλά"}
        # A contrast starts a new clause; a negation after "and" also must
        # not leak backwards into the preceding entity.
        coordinators = {"and", "in", "und", "e", "en", "και"}
        for idx in range(first - 1, left - 1, -1):
            if (
                tokens[idx].text in {",", ";", ":"}
                or tokens[idx].norm in contrast_words
                or "\n" in text[tokens[idx].end:tokens[idx + 1].start]
            ):
                left = idx + 1
                break
        for idx in range(last + 1, right):
            if (
                tokens[idx].text in {",", ";", ":"}
                or tokens[idx].norm in contrast_words | coordinators
                or "\n" in text[tokens[idx - 1].end:tokens[idx].start]
            ):
                right = idx
                break
        if left >= right:
            return ""
        return text[tokens[left].start:tokens[right - 1].end]

    def _rule_based_context(self, text: str, entity: Dict[str, Any], language: str) -> Dict[str, Any]:
        context = self._local_clause(text, entity)
        neg_phrases = MultilingualClinicalConfig.NEGATION_PHRASES.get(language, [])

        # 'Not excluded' indicates uncertainty, not either a confirmed
        # negation or an affirmed disease. These exceptions are scoped to
        # the same clause and resolved before generic negation phrases.
        uncertain_exceptions = [
            "not excluded", "cannot be excluded", "not ruled out",
            "niet uitgesloten", "non esclusa", "non escluso",
            "ni izključeno", "ni izključena", "nicht ausgeschlossen",
            "δεν αποκλείεται",
        ]
        positive_exceptions = [
            "not to stop", "not stop", "did not deny", "niet stoppen",
            "niet ontkend", "non interrompere", "ne preneha", "nicht absetzen",
        ]
        uncertain_status = [
            "suspected", "verdacht", "verdacht auf", "sospetta", "sospetto",
            "sum na", "ύποπτη", "ύποπτο",
        ]
        historical_status = ["historical", "historisch", "storico", "storica", "anamnestično"]
        negative_status = [
            "excluded", "uitgesloten", "esclusa", "escluso", "izključeno",
            "ausgeschlossen", "αποκλείστηκε",
        ]

        context_class = "AFFIRMED"
        if self._has_any_phrase(context, uncertain_exceptions):
            context_class = "UNCERTAIN"
        elif self._has_any_phrase(context, positive_exceptions):
            context_class = "AFFIRMED"
        elif self._has_any_phrase(context, neg_phrases):
            context_class = "NEGATED"
        elif self._has_any_phrase(context, negative_status):
            context_class = "NEGATED"
        elif self._has_any_phrase(context, uncertain_status):
            context_class = "UNCERTAIN"
        elif self._has_any_phrase(context, historical_status):
            context_class = "HISTORICAL"

        # These are heuristic rules, not a probabilistic model. Do not return
        # invented confidence values (0.70/0.80/etc.).
        return {"context_class": context_class, "context_source": "rule_fallback"}

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

    @staticmethod
    def _type(entity: Dict[str, Any]) -> str:
        return entity.get("clinical_type") or entity["label"]

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
        blocked = self.BLOCKED_IF_NEGATED.get(self._type(head), set())
        return rel_type not in blocked

    def build(self, entities: List[Dict[str, Any]], sentences: List[SentenceSpan]) -> List[Dict[str, Any]]:
        relations: List[Dict[str, Any]] = []

        for sentence in sentences:
            sent_entities = self._entities_in_sentence(entities, sentence)
            dates = [e for e in sent_entities if self._type(e) == "DATE"]
            values = [e for e in sent_entities if self._type(e) == "VALUE"]
            units = [e for e in sent_entities if self._type(e) == "UNIT"]
            durations = [e for e in sent_entities if self._type(e) == "DURATION"]
            frequencies = [e for e in sent_entities if self._type(e) == "FREQUENCY"]
            routes = [e for e in sent_entities if self._type(e) == "ROUTE"]
            statuses = [e for e in sent_entities if self._type(e) == "STATUS"]
            negations = [e for e in sent_entities if self._type(e) == "NEGATION"]

            measurements = [e for e in sent_entities if self._type(e) in self.MEASUREMENT_LABELS]
            observations = [e for e in sent_entities if self._type(e) in self.OBSERVATION_LABELS]
            drugs = [e for e in sent_entities if self._type(e) in self.DRUG_LABELS]
            conditions = [e for e in sent_entities if self._type(e) in self.CONDITION_LABELS]

            positive_heads = measurements + observations + drugs + conditions
            for head in positive_heads:
                if head.get("context_class") == "NEGATED":
                    neg_tail = self._find_negation_tail(head, negations)
                    if neg_tail is not None:
                        relations.append(self._relation("NEGATED", head, neg_tail, source=head.get("context_source", "context_classifier")))
                elif head.get("context_class") == "UNCERTAIN" and self._type(head) == "CONDITION":
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
    """Run the ORIGINAL post-NER pipeline on predictions from the BioNER engine."""

    def __init__(self, use_context_classifier: bool = False,
                 context_classifier_model: str = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli") -> None:
        self.enricher = TokenLexicalEnricher()
        self.context_classifier = EntityContextClassifier(
            use_model=use_context_classifier, model_name=context_classifier_model
        )
        self.relation_builder = ClinicalRelationBuilder()

    @staticmethod
    def _clinical_type(label: str) -> Optional[str]:
        normalized = MultilingualClinicalConfig.normalize_text(label)
        return MultilingualClinicalConfig.LABEL_NORMALIZATION.get(normalized)

    def run(self, text: str, predictions: Sequence[Any],
            language: Optional[str] = None,
            label_map: Optional[dict[str, str]] = None,
            existing_entities: Sequence[Any] = (),
            label_relations: Sequence[dict[str, str]] = (),
            date_label: Optional[str] = None) -> Dict[str, Any]:
        if language is None:
            language = MultilingualClinicalConfig.detect_language(text)
        if language not in MultilingualClinicalConfig.SUPPORTED_LANGS:
            language = "en"
        canonical = {k.casefold(): v for k, v in (label_map or {}).items()}

        def unpack(value: Any) -> dict:
            if isinstance(value, dict):
                return value
            if hasattr(value, "model_dump"):
                return value.model_dump()
            return dict(value)

        initial = []
        for item, is_existing in [*((item, False) for item in predictions),
                                  *((item, True) for item in existing_entities)]:
            ent = unpack(item)
            try:
                start, end = int(ent["start"]), int(ent["end"])
                label = str(ent["label"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (0 <= start < end <= len(text)):
                continue
            label = canonical.get(label.casefold(), label)
            initial.append({
                "start": start, "end": end, "text": text[start:end],
                "label": label, "score": ent.get("score"),
                "source": "existing_manual" if is_existing else "gliner",
                "clinical_type": self._clinical_type(label),
            })
        enriched_entities, tokens, sentences = self.enricher.enrich(text, initial, language)
        for ent in enriched_entities:
            if (ent.get("clinical_type") or ent["label"]) in {
                "DRUG", "CONDITION", "OBSERVATION", "MEASUREMENT"
            }:
                ent.update(self.context_classifier.classify(text, ent, language))

        relations = self.relation_builder.build(enriched_entities, sentences)
        relations.extend(self._configured_relations(enriched_entities, sentences, label_relations))
        seen = set()
        dedup = []
        for rel in relations:
            key = (rel.get("type"), rel["head"], rel["tail"])
            if key not in seen:
                seen.add(key)
                dedup.append(rel)
        return {"text": text, "language": language, "entities": enriched_entities, "relations": dedup}

    @staticmethod
    def _configured_relations(entities: List[dict], sentences: List[SentenceSpan],
                              label_relations: Sequence[dict[str, str]]) -> List[dict]:
        """Preserve the previous _link_configured_dataset_relations nearest-link fallback.

        For every configured directed pair, prefer the nearest right-hand match
        in the SAME sentence; if none exists use the nearest on the left.
        Include existing manually-annotated entities in the candidate set.
        """
        relmap: dict[str, set[str]] = {}
        for relation in label_relations:
            source, target = relation.get("from_label"), relation.get("to_label")
            if source and target:
                relmap.setdefault(source.casefold().strip(), set()).add(target.casefold().strip())
        relations = []
        for sentence in sentences:
            members = [e for e in entities if sentence.start <= e["start"] and e["end"] <= sentence.end]
            for head in members:
                for target_label in relmap.get(head["label"].casefold().strip(), ()):
                    candidates = [e for e in members if e["id"] != head["id"]
                                  and e["label"].casefold().strip() == target_label]
                    if not candidates:
                        continue
                    right = [e for e in candidates if e["start"] >= head["end"]]
                    pool = right or candidates
                    center = (head["start"] + head["end"]) / 2
                    target = min(pool, key=lambda e: abs((e["start"]+e["end"])/2-center))
                    relations.append({"type": "CONFIGURED", "head": head["id"],
                                      "tail": target["id"], "source": "dataset_relation"})
        return relations
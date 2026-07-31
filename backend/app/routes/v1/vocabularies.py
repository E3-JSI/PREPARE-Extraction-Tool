import os
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    File,
    UploadFile,
    BackgroundTasks,
)
from sqlalchemy import or_
from sqlmodel import Session, delete, insert, select, func, update

from app.core.database import engine, get_session, Vocabulary, Concept, User
from app.core.settings import settings
from app.library.file_parser import parse_concepts_file
from app.models_db import ProcessingStatus
from app.routes.v1.auth import get_current_user
from app.schemas import (
    ConceptCreate,
    ConceptOutput,
    ConceptsOutput,
    DistinctValuesOutput,
    MessageOutput,
    PaginationParams,
    ProcessingVocabularyStats,
    VocabulariesOutput,
    VocabularyOutput,
    VocabularyResponse,
    VocabularyUploadResponse,
    create_pagination_metadata,
)
from app.library.concept_indexer import indexer

# ================================================
# Route definitions
# ================================================

router = APIRouter()


# ================================================
# Helper functions
# ================================================


def verify_vocabulary_ownership(vocabulary: Vocabulary, user_id: int, db: Session):
    """Verify that the user owns the vocabulary or that it is a seed vocabulary."""
    seed_user_id = get_seed_user_id(db)

    if vocabulary.user_id == user_id:
        return

    if seed_user_id and vocabulary.user_id == seed_user_id:
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authorized to access this vocabulary",
    )

def verify_strict_vocabulary_ownership(vocabulary: Vocabulary, user_id: int):
    """Verify that the user owns the vocabulary."""
    if vocabulary.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this vocabulary",
        )

def get_seed_user_id(db: Session):
    return db.exec(
        select(User.id).where(User.username == "seed_system")
    ).first()

def get_owner_filter(current_user: User, db: Session):
    seed_user_id = get_seed_user_id(db)

    if seed_user_id:
        return or_(
            Vocabulary.user_id == current_user.id,
            Vocabulary.user_id == seed_user_id,
        )

    return Vocabulary.user_id == current_user.id


# ================================================
# Filter endpoints (must be before /{vocabulary_id})
# ================================================


@router.get(
    "/filters/domains",
    response_model=DistinctValuesOutput,
    status_code=status.HTTP_200_OK,
    summary="Get distinct domain values",
    description="Returns distinct domain_id values from concepts in user's vocabularies",
)
def get_distinct_domains(
    vocabulary_ids: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Get distinct domain values for filter dropdowns."""
    owner_filter = get_owner_filter(current_user, db)
    query = (
        select(Concept.domain_id)
        .distinct()
        .join(Vocabulary, Concept.vocabulary_id == Vocabulary.id)
        .where(owner_filter)
        .where(Concept.domain_id.isnot(None))
        .where(Concept.domain_id != "")
    )

    if vocabulary_ids:
        vocab_id_list = [
            int(vid.strip()) for vid in vocabulary_ids.split(",") if vid.strip()
        ]
        if vocab_id_list:
            query = query.where(Concept.vocabulary_id.in_(vocab_id_list))

    results = db.exec(query.order_by(Concept.domain_id)).all()
    return DistinctValuesOutput(values=results)


@router.get(
    "/filters/concept-classes",
    response_model=DistinctValuesOutput,
    status_code=status.HTTP_200_OK,
    summary="Get distinct concept class values",
    description="Returns distinct concept_class_id values from user's vocabularies",
)
def get_distinct_concept_classes(
    vocabulary_ids: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Get distinct concept class values for filter dropdowns."""
    owner_filter = get_owner_filter(current_user, db)
    query = (
        select(Concept.concept_class_id)
        .distinct()
        .join(Vocabulary, Concept.vocabulary_id == Vocabulary.id)
        .where(owner_filter)
        .where(Concept.concept_class_id.isnot(None))
        .where(Concept.concept_class_id != "")
    )

    if vocabulary_ids:
        vocab_id_list = [
            int(vid.strip()) for vid in vocabulary_ids.split(",") if vid.strip()
        ]
        if vocab_id_list:
            query = query.where(Concept.vocabulary_id.in_(vocab_id_list))

    results = db.exec(query.order_by(Concept.concept_class_id)).all()
    return DistinctValuesOutput(values=results)


# ================================================
# Vocabularies routes
# ================================================


@router.get(
    "/",
    response_model=VocabulariesOutput,
    status_code=status.HTTP_200_OK,
    summary="List all vocabularies",
    description="Retrieves a list of all vocabularies owned by the authenticated user",
    response_description="List of vocabularies with their metadata",
)
def get_vocabularies(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
    pagination: PaginationParams = Depends(),
):
    owner_filter = get_owner_filter(current_user, db)

    # Get total count (exclude DELETED)
    total = db.exec(
        select(func.count())
        .select_from(Vocabulary)
        .where(owner_filter)
        .where(Vocabulary.status != ProcessingStatus.DELETED)
    ).one()

    # Subquery: only count concepts for this user's vocabularies
    concept_counts_subquery = (
        select(Concept.vocabulary_id, func.count(Concept.id).label("count"))
        .join(Vocabulary, Concept.vocabulary_id == Vocabulary.id)
        .where(owner_filter)
        .group_by(Concept.vocabulary_id)
        .subquery()
    )

    # Get paginated vocabularies with concept counts in a single query
    vocabularies_with_counts = db.exec(
        select(
            Vocabulary,
            func.coalesce(concept_counts_subquery.c.count, 0).label("concept_count"),
        )
        .outerjoin(
            concept_counts_subquery,
            Vocabulary.id == concept_counts_subquery.c.vocabulary_id,
        )
        .where(owner_filter)
        .where(Vocabulary.status != ProcessingStatus.DELETED)
        .order_by(Vocabulary.id)
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all()

    vocabulary_responses = [
        VocabularyResponse(
            id=vocabulary.id,
            name=vocabulary.name,
            uploaded=vocabulary.uploaded,
            concept_count=concept_count,
            status=vocabulary.status,
            error_message=vocabulary.error_message,
        )
        for vocabulary, concept_count in vocabularies_with_counts
    ]

    return VocabulariesOutput(
        vocabularies=vocabulary_responses,
        pagination=create_pagination_metadata(
            total, pagination.limit, pagination.offset
        ),
    )


@router.post(
    "/",
    response_model=VocabularyUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create a new vocabulary",
    description="Creates a new vocabulary with its concepts and indexes them in Elasticsearch for semantic search",
    response_description="Confirmation message that the vocabulary was created successfully",
)
async def create_vocabulary(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type.",
        )

    # Reject obviously oversized uploads via Content-Length header
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file.size and file.size > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {settings.MAX_UPLOAD_SIZE_MB} MB.",
        )

    # save file to disk
    file_path = await save_upload_to_disk(file, ".csv")

    # start background ingestion
    background_tasks.add_task(ingest_vocabulary_background, file_path, current_user)

    vocabulary_response = VocabularyUploadResponse(
        status=ProcessingStatus.PENDING,
        message="Concept upload successfully started background task",
    )
    return vocabulary_response


async def save_upload_to_disk(file: UploadFile, suffix: str) -> str:
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    path = f"/tmp/{uuid4()}{suffix}"
    total = 0

    with open(path, "wb") as out:
        # read 1 MB at a time
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                os.unlink(path)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File too large. Maximum size is {settings.MAX_UPLOAD_SIZE_MB} MB.",
                )
            out.write(chunk)

    return path


def _filter_duplicates(db: Session, batch: list) -> list:
    """Remove concepts whose vocab_term_id already exists in their vocabulary."""
    # Group by vocabulary_id
    by_vocab = {}
    for c in batch:
        by_vocab.setdefault(c.vocabulary_id, []).append(c)

    new_concepts = []
    for vid, concepts in by_vocab.items():
        term_ids = [c.vocab_term_id for c in concepts]
        existing = set(
            db.exec(
                select(Concept.vocab_term_id).where(
                    Concept.vocabulary_id == vid,
                    Concept.vocab_term_id.in_(term_ids),
                )
            ).all()
        )
        new_concepts.extend(c for c in concepts if c.vocab_term_id not in existing)
    return new_concepts


def _insert_and_index_batch(
    db: Session, batch: list, new_vocab_ids: set, reused_inserted_ids: list
):
    """Insert a batch of Concepts via Core INSERT RETURNING and index in ES.

    Skips concepts that already exist (by vocab_term_id + vocabulary_id).

    Records (concept_id, vocab_id) for concepts inserted into REUSED
    (pre-existing) vocabularies in ``reused_inserted_ids`` so a later failure
    can roll them back from both PostgreSQL and Elasticsearch. Tracking happens
    BEFORE indexing so a mid-index failure still leaves a complete record.
    """
    batch = _filter_duplicates(db, batch)
    if not batch:
        return

    concept_dicts = [
        {
            "vocab_term_id": c.vocab_term_id,
            "vocab_term_name": c.vocab_term_name,
            "domain_id": c.domain_id,
            "concept_class_id": c.concept_class_id,
            "standard_concept": c.standard_concept,
            "concept_code": c.concept_code,
            "valid_start_date": c.valid_start_date,
            "valid_end_date": c.valid_end_date,
            "invalid_reason": c.invalid_reason,
            "vocabulary_id": c.vocabulary_id,
        }
        for c in batch
    ]
    result = db.execute(insert(Concept).returning(Concept.id), concept_dicts)
    ids = result.scalars().all()
    db.commit()
    for concept, concept_id in zip(batch, ids):
        concept.id = concept_id

    reused_inserted_ids.extend(
        (concept_id, concept.vocabulary_id)
        for concept, concept_id in zip(batch, ids)
        if concept.vocabulary_id not in new_vocab_ids
    )

    indexer.add_bulk_to_index(batch)


def ingest_vocabulary_background(file_path: str, current_user: User):
    db = Session(engine)

    REQUIRED_COLUMNS = [
        "concept_id",
        "concept_name",
        "domain_id",
        "vocabulary_id",
        "concept_class_id",
        "standard_concept",
        "concept_code",
        "valid_start_date",
        "valid_end_date",
        "invalid_reason",
    ]

    UNWANTED_IDS = [
        "Korean Revenue Code",
        "Cost Type",
        "UB04 Pt dis status",
        "Observation Type",
        "Concept Class",
        "UB04 Pri Typ of Adm",
        "Visit Type",
        "Sponsor",
        "Relationship",
        "SOPT",
        "Meas Type",
        "US Census",
        "Language",
        "Note Type",
        "Condition Status",
        "Procedure Type",
        "Vocabulary",
        "Obs Period Type",
        "Type Concept",
        "Plan Stop Reason",
        "UCUM",
        "CDM",
        "Metadata",
        "OSM",
        "Plan",
        "UB04 Point of Origin",
        "Cost",
        "UB04 Typ bill",
        "Episode",
        "Death Type",
        "Condition Type",
        "Device Type",
        "Drug Type",
        "Visit",
        "Domain",
        "None",
    ]

    vocabularies = {}  # vocab_name -> vocab_id
    new_vocab_ids = set()  # only IDs for newly created vocabularies
    # (concept_id, vocab_id) inserted this run into REUSED vocabularies, so a
    # mid-ingest failure can be rolled back from both PostgreSQL and ES.
    reused_inserted_ids = []
    seed_user_id = get_seed_user_id(db)
    try:

        # start ingesting
        BATCH_SIZE = 5000
        batch = []
        total = 0
        for concept, vocab_name in parse_concepts_file(
            file_path, REQUIRED_COLUMNS, UNWANTED_IDS
        ):
            if vocab_name in vocabularies:
                concept.vocabulary_id = vocabularies[vocab_name]
            else:
                # Check for existing vocabulary (same name + user, DONE)
                existing = db.exec(
                    select(Vocabulary).where(
                        Vocabulary.name == vocab_name,
                        Vocabulary.user_id == current_user.id,
                        Vocabulary.status == ProcessingStatus.DONE,
                    )
                ).first()

                # Check for existing vocabulary from seed user
                if seed_user_id is not None:
                    existing_seed_vocabulary = db.exec(
                        select(Vocabulary).where(
                            Vocabulary.name == vocab_name,
                            Vocabulary.user_id == seed_user_id,
                            Vocabulary.status == ProcessingStatus.DONE,
                        )
                    ).first()
                    if existing_seed_vocabulary:
                        print(f"Not possible to modify seed Vocabulary '{vocab_name}' (id={existing_seed_vocabulary.id}).")
                        continue

                if existing:
                    vocab_id = existing.id
                    print(f"Reusing existing vocabulary '{vocab_name}' (id={vocab_id})")
                else:
                    # create a new Vocabulary
                    vocabulary = Vocabulary(name=vocab_name, user_id=current_user.id)
                    db.add(vocabulary)
                    db.commit()
                    db.refresh(vocabulary)
                    vocab_id = vocabulary.id
                    # create new ES index
                    indexer.create_concept_index(vocab_id)
                    new_vocab_ids.add(vocab_id)

                concept.vocabulary_id = vocab_id
                vocabularies[vocab_name] = vocab_id

            batch.append(concept)

            if len(batch) >= BATCH_SIZE:
                _insert_and_index_batch(
                    db, batch, new_vocab_ids, reused_inserted_ids
                )
                total += len(batch)
                batch.clear()
                print("Rows saved:", total)

        if batch:
            _insert_and_index_batch(db, batch, new_vocab_ids, reused_inserted_ids)
            total += len(batch)
            print("Rows saved:", total, "-> ALL")

        # Mark only newly created vocabularies as DONE
        if new_vocab_ids:
            db.exec(
                update(Vocabulary)
                .where(Vocabulary.id.in_(list(new_vocab_ids)))
                .values(status=ProcessingStatus.DONE)
            )
            db.commit()

    except Exception as e:
        import traceback

        traceback.print_exc()
        # failure cleanup
        db.rollback()

        error_msg = str(e)

        # Newly created vocabularies: mark FAILED and drop their whole ES index.
        if new_vocab_ids:
            db.exec(
                update(Vocabulary)
                .where(Vocabulary.id.in_(list(new_vocab_ids)))
                .values(status=ProcessingStatus.FAILED, error_message=error_msg)
            )
            db.commit()

            for vocab_id in new_vocab_ids:
                try:
                    indexer.delete_index(vocab_id)
                except Exception as es_err:
                    print(f"Failed to delete ES index for vocab {vocab_id}: {es_err}")

        # Reused vocabularies stay intact, but the concepts added THIS run must
        # be rolled back from both PostgreSQL and ES so the (committed) partial
        # ingest does not leave the two stores inconsistent.
        if reused_inserted_ids:
            db.exec(
                delete(Concept).where(
                    Concept.id.in_([cid for cid, _ in reused_inserted_ids])
                )
            )
            db.commit()

            for concept_id, vocab_id in reused_inserted_ids:
                try:
                    indexer.delete_concept_from_index(vocab_id, concept_id)
                except Exception as es_err:
                    print(
                        f"Failed to delete ES doc {concept_id} "
                        f"from vocab {vocab_id}: {es_err}"
                    )

    finally:
        db.close()


@router.get(
    "/processing/stats",
    response_model=ProcessingVocabularyStats,
    status_code=status.HTTP_200_OK,
    summary="Get processing vocabulary stats",
    description="Returns the number of vocabularies in PROCESSING state and the total number of uploaded concepts",
)
def get_processing_vocabulary_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    # count vocabularies in PROCESSING
    vocab_count = db.exec(
        select(func.count(Vocabulary.id)).where(
            Vocabulary.user_id == current_user.id,
            Vocabulary.status == ProcessingStatus.PROCESSING,
        )
    ).one()

    # sum concepts across those vocabularies
    concept_count = db.exec(
        select(func.count(Concept.id))
        .join(Vocabulary, Concept.vocabulary_id == Vocabulary.id)
        .where(
            Vocabulary.user_id == current_user.id,
            Vocabulary.status == ProcessingStatus.PROCESSING,
        )
    ).one()

    return ProcessingVocabularyStats(
        processing_vocabularies=vocab_count or 0,
        total_concepts=concept_count or 0,
    )


@router.get(
    "/{vocabulary_id}",
    response_model=VocabularyOutput,
    status_code=status.HTTP_200_OK,
    summary="Get a specific vocabulary",
    description="Retrieves a single vocabulary by its ID",
    response_description="The requested vocabulary with its metadata",
)
def get_vocabulary(
    vocabulary_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    vocabulary = db.get(Vocabulary, vocabulary_id)
    if vocabulary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vocabulary not found"
        )
    verify_vocabulary_ownership(vocabulary, current_user.id, db)

    vocabulary_response = VocabularyResponse(
        id=vocabulary.id,
        name=vocabulary.name,
        uploaded=vocabulary.uploaded,
        concept_count=db.exec(
            select(func.count(Concept.id)).where(Concept.vocabulary_id == vocabulary.id)
        ).one(),
        status=vocabulary.status,
        error_message=vocabulary.error_message,
    )
    return VocabularyOutput(vocabulary=vocabulary_response)


@router.delete(
    "/{vocabulary_id}",
    response_model=MessageOutput,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Delete a vocabulary",
    description="Deletes a vocabulary, its concepts, and removes it from the Elasticsearch index",
    response_description="Confirmation message that the vocabulary deletion started",
)
def delete_vocabulary(
    background_tasks: BackgroundTasks,
    vocabulary_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    vocabulary = db.get(Vocabulary, vocabulary_id)
    if vocabulary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vocabulary not found"
        )

    verify_strict_vocabulary_ownership(vocabulary, current_user.id)
    vocabulary.status = ProcessingStatus.DELETED
    db.commit()

    # start background deletion
    background_tasks.add_task(delete_vocabulary_background, vocabulary_id)

    return MessageOutput(message="Vocabulary deletion started in the background")


def delete_vocabulary_background(vocabulary_id: int):
    db = Session(engine)
    try:
        # Delete ES index first (idempotent — checks exists before deleting).
        # Doing this first avoids orphaned ES indices if DB delete succeeds
        # but ES delete fails on a subsequent retry.
        indexer.delete_index(vocabulary_id)

        # Single SQL DELETE — PostgreSQL ON DELETE CASCADE handles
        # Concept and SourceToConceptMap rows at the DB level,
        # avoiding loading all children into Python memory.
        db.exec(delete(Vocabulary).where(Vocabulary.id == vocabulary_id))
        db.commit()

        print(f"Successfully deleted vocabulary {vocabulary_id}")

    except Exception as e:
        db.rollback()
        print(f"Failed to delete vocabulary {vocabulary_id}: {e}")
    finally:
        db.close()


# ================================================
# Concepts routes
# ================================================


@router.get(
    "/{vocabulary_id}/concepts/search",
    response_model=ConceptsOutput,
    status_code=status.HTTP_200_OK,
    summary="Search concepts in a vocabulary",
    description="Searches concepts in a vocabulary using Elasticsearch hybrid search",
    response_description="List of matching concepts with pagination",
)
def search_vocabulary_concepts(
    vocabulary_id: int,
    query: str,
    domain_id: str = None,
    concept_class_id: str = None,
    standard_concept: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
    pagination: PaginationParams = Depends(),
):
    """Search concepts in a vocabulary using Elasticsearch."""
    vocabulary = db.get(Vocabulary, vocabulary_id)
    if vocabulary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vocabulary not found"
        )
    verify_vocabulary_ownership(vocabulary, current_user.id, db)

    # Search using Elasticsearch
    es_results, total_hits = indexer.search_concepts(
        query_text=query,
        vocab_ids=[vocabulary_id],
        limit=pagination.limit,
        offset=pagination.offset,
        domain_id=domain_id,
        concept_class_id=concept_class_id,
        standard_concept=standard_concept,
    )

    # Get concept details from database
    concept_ids = [r["concept_id"] for r in es_results]
    if concept_ids:
        concepts = db.exec(select(Concept).where(Concept.id.in_(concept_ids))).all()
        # Preserve ES ordering
        concept_map = {c.id: c for c in concepts}
        concepts = [concept_map[cid] for cid in concept_ids if cid in concept_map]
    else:
        concepts = []

    return ConceptsOutput(
        concepts=concepts,
        pagination=create_pagination_metadata(
            total_hits, pagination.limit, pagination.offset
        ),
    )


@router.get(
    "/{vocabulary_id}/concepts",
    response_model=ConceptsOutput,
    status_code=status.HTTP_200_OK,
    summary="List all concepts in a vocabulary",
    description="Retrieves all concepts belonging to a specific vocabulary",
    response_description="List of concepts in the vocabulary",
)
def get_concepts(
    vocabulary_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
    pagination: PaginationParams = Depends(),
):
    vocabulary = db.get(Vocabulary, vocabulary_id)
    if vocabulary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vocabulary not found"
        )
    verify_vocabulary_ownership(vocabulary, current_user.id, db)

    # Get total count
    total = db.exec(
        select(func.count())
        .select_from(Concept)
        .where(Concept.vocabulary_id == vocabulary_id)
    ).one()

    # Get paginated concepts
    concepts = db.exec(
        select(Concept)
        .where(Concept.vocabulary_id == vocabulary_id)
        .order_by(Concept.id)
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all()

    return ConceptsOutput(
        concepts=concepts,
        pagination=create_pagination_metadata(
            total, pagination.limit, pagination.offset
        ),
    )


@router.post(
    "/{vocabulary_id}/concepts",
    response_model=MessageOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Add a concept to a vocabulary",
    description="Creates a new concept and adds it to the specified vocabulary and its Elasticsearch index",
    response_description="Confirmation message that the concept was added successfully",
)
def add_concept(
    vocabulary_id: int,
    concept: ConceptCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    vocabulary = db.get(Vocabulary, vocabulary_id)
    if vocabulary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vocabulary not found"
        )
    verify_vocabulary_ownership(vocabulary, current_user.id, db)

    new_concept = Concept(
        vocabulary_id=vocabulary_id,
        vocab_term_id=concept.vocab_term_id,
        vocab_term_name=concept.vocab_term_name,
        domain_id=concept.domain_id,
        concept_class_id=concept.concept_class_id,
        standard_concept=concept.standard_concept,
        concept_code=concept.concept_code,
        valid_start_date=concept.valid_start_date,
        valid_end_date=concept.valid_end_date,
        invalid_reason=concept.invalid_reason,
    )

    db.add(new_concept)
    db.commit()
    db.refresh(new_concept)

    indexer.add_concept_to_index(vocabulary_id, new_concept)

    return MessageOutput(message="Concept added successfully")


@router.get(
    "/{vocabulary_id}/concepts/{concept_id}",
    response_model=ConceptOutput,
    status_code=status.HTTP_200_OK,
    summary="Get a specific concept",
    description="Retrieves a single concept by its ID from a specific vocabulary",
    response_description="The requested concept",
)
def get_concept(
    vocabulary_id: int,
    concept_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    vocabulary = db.get(Vocabulary, vocabulary_id)
    if vocabulary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vocabulary not found"
        )
    verify_vocabulary_ownership(vocabulary, current_user.id, db)

    statement = (
        select(Concept)
        .where(Concept.vocabulary_id == vocabulary_id)
        .where(Concept.id == concept_id)
    )
    concept = db.exec(statement).one_or_none()

    if concept is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Concept not found"
        )

    return ConceptOutput(concept=concept)


@router.delete(
    "/{vocabulary_id}/concepts/{concept_id}",
    response_model=MessageOutput,
    status_code=status.HTTP_200_OK,
    summary="Delete a concept",
    description="Deletes a specific concept from a vocabulary and removes it from the Elasticsearch index",
    response_description="Confirmation message that the concept was deleted successfully",
)
def delete_concept(
    vocabulary_id: int,
    concept_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    vocabulary = db.get(Vocabulary, vocabulary_id)
    if vocabulary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vocabulary not found"
        )
    verify_strict_vocabulary_ownership(vocabulary, current_user.id)

    statement = (
        select(Concept)
        .where(Concept.vocabulary_id == vocabulary_id)
        .where(Concept.id == concept_id)
    )
    concept = db.exec(statement).one_or_none()

    if concept is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Concept not found"
        )

    db.delete(concept)
    db.commit()

    indexer.delete_concept_from_index(vocabulary_id, concept_id)

    return MessageOutput(message="Concept deleted successfully")

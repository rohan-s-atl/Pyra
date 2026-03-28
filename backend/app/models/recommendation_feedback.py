from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.core.database import Base


class RecommendationFeedback(Base):
    """
    Stores dispatcher feedback on AI recommendations.

    outcome:
      - "accepted"  — dispatcher approved the recommendation as-is
      - "rejected"  — dispatcher dismissed the recommendation entirely
      - "overridden" — dispatcher dispatched different units than recommended

    confidence_reported is the AI confidence score at time of feedback.
    override_unit_ids is a comma-separated list of actual unit IDs dispatched
    when the recommendation was overridden.
    """
    __tablename__ = "recommendation_feedback"

    id              = Column(String, primary_key=True, index=True)
    incident_id     = Column(String, ForeignKey("incidents.id"), nullable=False, index=True)
    recommendation_id = Column(String, nullable=True)   # matches Recommendation.id if persisted
    actor           = Column(String, nullable=False)     # username
    actor_role      = Column(String, nullable=True)
    outcome         = Column(String, nullable=False)     # accepted | rejected | overridden
    override_unit_ids = Column(Text, nullable=True)      # CSV of actual unit IDs when overridden
    reason          = Column(Text, nullable=True)        # optional free-text reason
    confidence_reported = Column(String, nullable=True)  # AI confidence at time of feedback
    recorded_at     = Column(DateTime, nullable=False, index=True)

    incident = relationship("Incident")

    __table_args__ = (
        Index("idx_rec_feedback_incident", "incident_id", "recorded_at"),
        Index("idx_rec_feedback_outcome",  "outcome"),
    )

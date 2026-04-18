"""
training — Synthetic data generation and model fine-tuning utilities.

Modules:
    synthetic_data — Teacher-Student LLM pipeline for generating training data
"""

from .synthetic_data import SyntheticDataGenerator, TeacherStudentPipeline

__all__ = ["SyntheticDataGenerator", "TeacherStudentPipeline"]

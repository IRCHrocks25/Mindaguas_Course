"""
Chatbot training utilities - extract lesson content and send to training webhook.
"""
import requests
from django.utils import timezone

TRAINING_WEBHOOK_URL = 'https://katalyst-crm2.fly.dev/webhook/425e8e67-2aa6-4c50-b67f-0162e2496b51'


def editorjs_to_plain_text(content):
    """Extract plain text from Editor.js content blocks for use as transcript."""
    if not content or not isinstance(content, dict):
        return ""
    blocks = content.get('blocks', [])
    parts = []
    for block in blocks:
        block_type = block.get('type', '')
        data = block.get('data', {})
        if block_type == 'paragraph':
            text = data.get('text', '')
            if text:
                parts.append(text)
        elif block_type == 'header':
            text = data.get('text', '')
            if text:
                parts.append(text)
        elif block_type == 'list':
            items = data.get('items', [])
            for item in items:
                if isinstance(item, dict):
                    text = item.get('content') or item.get('text', '')
                else:
                    text = str(item)
                if text:
                    parts.append(f"• {text}" if text else text)
        elif block_type == 'quote':
            text = data.get('text', '')
            if text:
                parts.append(f'"{text}"')
    return '\n\n'.join(parts)


def extract_lesson_transcript(lesson):
    """
    Extract transcript text from a lesson for chatbot training.
    Uses: transcription (from video), or content (Editor.js) + ai_full_description.
    """
    # Prefer video transcription if available
    if lesson.transcription and lesson.transcription.strip():
        return lesson.transcription.strip()

    parts = []

    # Add AI full description (rich lesson overview)
    if lesson.ai_full_description:
        parts.append(lesson.ai_full_description.strip())

    # Add title and description
    if lesson.title:
        parts.insert(0, f"Lesson: {lesson.title}")
    if lesson.description:
        parts.append(lesson.description.strip())

    # Extract text from Editor.js content blocks
    if lesson.content:
        content_text = editorjs_to_plain_text(lesson.content)
        if content_text:
            parts.append(content_text)

    transcript = '\n\n'.join(p for p in parts if p)
    return transcript.strip()


def send_lesson_to_chatbot_training(lesson, transcript=None, timeout=30):
    """
    Send lesson transcript to the training webhook and update lesson status.

    Args:
        lesson: Lesson model instance
        transcript: Optional transcript text. If None, extracts from lesson.
        timeout: Request timeout in seconds

    Returns:
        tuple: (success: bool, error: str|None)
    """
    transcript = transcript or extract_lesson_transcript(lesson)
    if not transcript:
        return False, 'No transcript content available (add description, transcription, or content)'

    lesson.transcription = transcript
    lesson.ai_chatbot_training_status = 'training'
    lesson.save(update_fields=['transcription', 'ai_chatbot_training_status'])

    payload = {
        'transcript': transcript,
        'lesson_id': lesson.id,
        'lesson_title': lesson.title,
        'course_name': lesson.course.name,
        'lesson_slug': lesson.slug,
    }

    try:
        response = requests.post(
            TRAINING_WEBHOOK_URL,
            json=payload,
            timeout=timeout,
            headers={'Content-Type': 'application/json'}
        )

        if response.status_code == 200:
            response_data = response.json() if response.content else {}
            chatbot_webhook_id = (
                response_data.get('chatbot_webhook_id') or
                response_data.get('webhook_id') or
                response_data.get('id')
            )
            if chatbot_webhook_id:
                lesson.ai_chatbot_webhook_id = str(chatbot_webhook_id)
            lesson.ai_chatbot_training_status = 'trained'
            lesson.ai_chatbot_trained_at = timezone.now()
            lesson.ai_chatbot_enabled = True
            lesson.ai_chatbot_training_error = ''
            lesson.save(update_fields=[
                'ai_chatbot_webhook_id', 'ai_chatbot_training_status',
                'ai_chatbot_trained_at', 'ai_chatbot_enabled', 'ai_chatbot_training_error'
            ])
            return True, None
        else:
            err_msg = f"Webhook returned status {response.status_code}: {response.text[:500]}"
            lesson.ai_chatbot_training_status = 'failed'
            lesson.ai_chatbot_training_error = err_msg
            lesson.save(update_fields=['ai_chatbot_training_status', 'ai_chatbot_training_error'])
            return False, err_msg

    except requests.exceptions.RequestException as e:
        lesson.ai_chatbot_training_status = 'failed'
        lesson.ai_chatbot_training_error = str(e)
        lesson.save(update_fields=['ai_chatbot_training_status', 'ai_chatbot_training_error'])
        return False, str(e)

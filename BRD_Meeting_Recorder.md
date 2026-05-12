# BRD: Revvy Meeting Recorder & Summariser
**Version:** 1.0  
**Author:** Ling Ling  
**Date:** 2026-05-12  
**Status:** Draft

---

## 1. Problem Statement

Leaders in the Commercial BU run back-to-back meetings and consistently lose track of decisions and action items discussed. Meeting notes are either not taken, incomplete, or never distributed. This leads to:
- Follow-ups being missed or delayed
- Leaders forgetting commitments made in meetings
- No accountability trail for action items
- Team members unaware of decisions that affect them

---

## 2. Objective

Enable Revvy to automatically convert meeting content into a structured summary and action item list, then post it to the designated Lark Leader Group — with zero manual effort from the leader.

---

## 3. Scope

| In Scope | Out of Scope |
|---|---|
| Meeting transcript → summary + action items | Live real-time transcription during meeting |
| Post output to Lark Leader Group | Tracking whether action items are completed |
| Support two input methods (see Section 5) | Integration with external CRM |
| Tag action item owners by name | Automated follow-up reminders (separate use case) |

---

## 4. Users

| User | Role | Need |
|---|---|---|
| Ling Ling (BU Head) | Initiator | Upload/paste meeting content, review output |
| Leaders (HODs) | Recipients | Receive clean summary + action items in Lark group |
| Account Managers | Indirect recipients | Aware of decisions that affect their work |

---

## 5. Solution Approaches

Two input methods will be supported. The user chooses whichever fits the meeting context.

### Approach A — Paste Transcript (Recommended Starting Point)
**How it works:**
1. User records meeting using any AI transcription tool (e.g., Plaud, Otter.ai, Lark's built-in recording, or phone voice memo + transcription app)
2. User copies the transcript text
3. User sends it to Revvy in Lark chat with the command: `/summarise [paste transcript here]`
4. Revvy processes it and posts the structured output to the Leader Group

**Pros:** Simple to build, no audio processing needed, works with any recording tool  
**Cons:** Manual copy-paste step required

### Approach B — Upload Audio/File to Revvy
**How it works:**
1. User uploads audio file or transcript file directly to Revvy in Lark chat
2. Revvy extracts text (from file) or transcribes audio (via Whisper API)
3. Revvy processes and posts output to Leader Group

**Pros:** More seamless, fewer steps  
**Cons:** More complex to build, audio transcription has cost (Whisper API ~$0.006/min)

**Recommendation:** Build Approach A first. Migrate to Approach B once Approach A is validated.

---

## 6. Functional Requirements

### 6.1 Input
- Revvy accepts a transcript via Lark direct message using the `/summarise` command
- Transcript can be in any language (English/Malay/Chinese mixed is acceptable)
- Minimum transcript length: 100 words

### 6.2 Processing
Revvy must extract and structure the following from the transcript:

| Output Field | Description | Example |
|---|---|---|
| Meeting Title | Auto-detected from context | "Leader Morning Meeting" |
| Date & Time | Extracted if mentioned, else use message timestamp | "12 May 2026, 9:30 AM" |
| Attendees | Names mentioned in transcript | "Ling Ling, Ray, Dandy, Reagen" |
| Key Decisions | Bullet list of decisions made | "Approved Q3 hiring plan for 5 new AMs" |
| Action Items | Each item with owner + deadline | "Ray to send client proposal by Friday" |
| Summary | 3–5 sentence overview of the meeting | Free-form prose |

### 6.3 Output
- Revvy posts the structured summary to the **Lark Leader Group** (group chat ID to be configured)
- Format must be clean and readable in Lark (no raw JSON, no jargon)
- Revvy also replies to the user in DM confirming: "✅ Meeting summary posted to Leader Group!"

### 6.4 Commands
| Command | Action |
|---|---|
| `/summarise [text]` | Process transcript and post to Leader Group |
| `/summarise preview` | Process transcript but only send to user DM (for review before posting) |

---

## 7. Output Format (Lark Message Template)

```
📋 MEETING SUMMARY
──────────────────
📅 Date: [date]
👥 Attendees: [names]

🧠 KEY DECISIONS
• [decision 1]
• [decision 2]

✅ ACTION ITEMS
• [Owner]: [action] → by [deadline]
• [Owner]: [action] → by [deadline]

📝 SUMMARY
[3-5 sentence overview]

— Posted by Revvy 🤖
```

---

## 8. Technical Requirements

### 8.1 Components Needed
| Component | Tool/Service | Status |
|---|---|---|
| Lark Bot (message listener) | lark-oapi (existing) | ✅ Done |
| AI summarisation engine | Groq / Llama 3.1 (existing) | ✅ Done |
| Post to Lark Group Chat | Lark IM API (chat_id) | 🔲 To Build |
| Command parser (`/summarise`) | Python string parsing | 🔲 To Build |
| Preview mode | DM reply logic | 🔲 To Build |

### 8.2 Configuration Required
- `LEADER_GROUP_CHAT_ID` — Lark group chat ID of the Leader Group (to be added to `.env`)

### 8.3 Tech Stack
- Language: Python 3.x
- Lark SDK: lark-oapi
- AI: Groq API (llama-3.1-8b-instant) — free tier
- Hosting: Local Mac (Phase 1), move to cloud server (Phase 2)

---

## 9. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Transcript quality is poor (background noise, mixed language) | Summary is inaccurate | Prompt engineering to handle noisy input; user reviews before posting |
| Wrong action item owner tagged | Confusion / missed task | Use `/summarise preview` to review before posting to group |
| Leader Group ID misconfigured | Posts to wrong group | Test with a dummy group first before pointing to real Leader Group |
| Transcript too long for single Lark message | Message gets cut off | Split into multiple messages if output exceeds 3,000 characters |

---

## 10. Success Metrics

| Metric | Target |
|---|---|
| Time from meeting end to summary posted | < 3 minutes |
| Leader satisfaction with summary accuracy | 8/10 or above |
| Action items captured per meeting | ≥ 80% of actual items discussed |
| Adoption | Used in ≥ 3 leader meetings per week within 2 weeks of launch |

---

## 11. Timeline

| Phase | Task | Duration |
|---|---|---|
| Phase 1 | Build `/summarise` command + AI processing | 1–2 days |
| Phase 1 | Configure Leader Group chat ID + post to group | 1 day |
| Phase 1 | Test with real meeting transcript | 1 day |
| Phase 2 | Add `/summarise preview` mode | 1 day |
| Phase 3 | Add Approach B (file/audio upload) | 1–2 weeks |

---

## 12. Open Questions

1. Which Lark group is the "Leader Group"? Need the chat ID.
2. Should the summary be posted automatically or require a `/confirm` step?
3. Should Revvy tag action item owners using their Lark @mention?
4. Who has permission to use `/summarise`? All users or only specific leaders?

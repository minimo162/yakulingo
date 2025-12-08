# M3 Expressive Design Proposals for YakuLingo

These recommendations translate the ideas from Google's Material Design 3 "Expressive" guidance into actionable updates for YakuLingo's UI. They aim to make translation workflows feel confident, friendly, and focused while keeping accessibility and productivity top of mind.

## Design Intent
- **Expressive yet trustworthy**: Lean into richer color, shape, and typography to give the app personality without sacrificing clarity for professional translation tasks.
- **Guided flows**: Use hierarchy and motion to emphasize the "input → translate → review → export" sequence across both text and file translation.
- **Accessible by default**: Ensure expressive elements maintain AA contrast, predictable focus order, and screen reader clarity.

## High-Impact Changes
1. **Color & Elevation**
   - Adopt an expressive tonal palette with deeper accent hues for primary actions (e.g., "Translate"/"Translate File") and a calmer secondary tone for utilities (history, glossary toggles).
   - Use surface elevation to separate key stages: input panel at `surface-container-low`, result panel at `surface-container`, and dialogs at `surface-container-high`. Soft shadows reinforce depth without clutter.
   - Introduce tonal overlays for drag-and-drop file targets to signal readiness states (idle/hover/error).

2. **Typography**
   - Shift to M3 type scale: `Headline Small` for page titles, `Title Medium` for tab labels, `Body Large` for primary text, and `Label Large` for buttons. Reserve `Label Medium` for chips and filters.
   - Increase line height in translation results for readability, especially bilingual outputs.
   - Use monospace or tabular numeral styles for token counts, character limits, and timestamps in history.

3. **Shape & Layout**
   - Round primary containers to `12dp` and inputs/cards to `8dp` for a softer, approachable feel consistent with M3 Expressive.
   - Provide more generous spacing between the input area and result area; align padding to the 8dp grid for consistency.
   - Convert the main navigation to a **navigation rail** on desktop widths with clear section icons (Text, File, History, Settings), retaining a bottom bar on narrow layouts.

4. **Component Styling**
   - **Buttons**: Use `filled` style for primary translation actions, `tonal` for secondary (e.g., "Use bundled glossary"), and `text` for inline helpers. Add leading icons to emphasize intent (play/send for translate, upload for file translation).
   - **Chips & Filters**: Replace toggle switches for glossary/export options with filter chips to align with M3 Expressive emphasis on compact, glanceable controls.
   - **Cards**: Wrap translation history entries in elevated cards with a prominent title (source filename/text snippet), secondary metadata, and a trailing action cluster (open/export/re-run).

5. **Motion & Feedback**
   - Apply subtle scale/opacity transitions when results render to cue completion without delaying interaction.
   - For file uploads, animate progress with determinate linear indicators and status chips (queued → processing → done). Use color transitions to reinforce status changes.
   - Provide micro-interactions for glossary toggles and inline refinement requests (e.g., ripple + tonal shift) to communicate state.

6. **States & Error Handling**
   - Add clear empty states with illustration/emoji and guidance for Text, File, and History views. Keep them short and localized.
   - Highlight validation errors (oversized files, missing Copilot access) with a strong error tonal color, icon, and concise remediation steps.
   - Offer inline recovery actions ("Retry", "Change file", "Open settings") in the error surface to reduce user friction.

7. **Accessibility & Internationalization**
   - Ensure minimum 4.5:1 contrast for body text and 3:1 for large headlines; verify accent colors against both light and dark schemes.
   - Support dynamic type scaling by respecting relative sizing tokens; avoid pixel-locked containers for translation text.
   - Mirror spacing and alignment rules for both JP→EN and EN→JP flows; keep RTL readiness in mind for future languages.

## Page-Level Layout Suggestions
- **Text Translation**
  - Two-column layout on desktop: left input card (headline, text field, helper chips for style), right output card with tabs for "Translation", "Notes", and "Inline tweaks".
  - Sticky action bar at the bottom of the input card with primary/secondary buttons and character counter.

- **File Translation**
  - Elevated dropzone with a dashed outline and expressive overlay on hover; include quick links to supported formats.
  - Timeline-style status area showing each stage (analyze → translate → export). Pair with status chips and inline download buttons when ready.

- **History & Settings**
  - Grid/list toggle for history cards; emphasize quick actions (reopen, export glossary) via tonal buttons.
  - Settings grouped into "Translation behavior", "Output", and "Updates" using segmented cards; add inline descriptions to reduce modal depth.

## Implementation Priorities
- Start with **color tokens** and **typography scale** to set the expressive foundation.
- Update **navigation** and **action bars** to clarify the primary tasks.
- Introduce **empty/error state components** for the three core views (Text, File, History).
- Add **motion tokens** for result rendering and file upload progress once visuals are stable.

These changes should bring the app closer to the expressive Material 3 direction while keeping translators efficient and confident.

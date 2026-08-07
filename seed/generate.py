"""Generate deterministic, visibly synthetic MemoryLedger demo data."""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import tiktoken

from app.memory_types import tier_for


RNG_SEED = 20260806
GENERATED_AT = "2026-08-06T00:00:00Z"
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "seed"
AGENT_ID = "memoryledger-tutor"
APP_ID = "memoryledger"
PROJECT_ID = "hackathon"


def _session_times(offset_minutes: int = 0) -> list[datetime]:
    """Return 23 weekday-evening sessions across the eight demo weeks."""
    result: list[datetime] = []
    first_monday = date(2026, 6, 15)
    for week in range(8):
        for day_offset, hour in ((0, 18), (2, 19), (4, 17)):
            day = first_monday + timedelta(days=week * 7 + day_offset)
            if day > date(2026, 8, 5):
                continue
            result.append(
                datetime.combine(day, time(hour, 10), tzinfo=timezone.utc)
                + timedelta(minutes=offset_minutes)
            )
    return result


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _memory_id(user_id: str, memory_type: str, content: str) -> str:
    digest = hashlib.sha256(f"{user_id}|{memory_type}|{content}".encode()).hexdigest()[:8]
    return f"mem_{digest}"


def _memory(
    *,
    rng: random.Random,
    user_id: str,
    memory_type: str,
    content: str,
    timestamp: datetime,
    metadata: dict[str, Any],
    session_id: str | None = None,
) -> dict[str, Any]:
    if (memory_type == "episode") != (session_id is not None):
        raise ValueError("session_id must be set if and only if memory_type is episode")
    return {
        "memory_id": _memory_id(user_id, memory_type, content),
        "memory_type": memory_type,
        "content": content,
        "user_id": user_id,
        "agent_id": AGENT_ID,
        "app_id": APP_ID,
        "project_id": PROJECT_ID,
        "session_id": session_id,
        "score": round(rng.uniform(0.58, 0.97), 2),
        "created_at": _iso(timestamp),
        "updated_at": _iso(timestamp),
        "metadata": metadata,
    }


MAYA_SKILLS = [
    "When Maya asks for an answer directly, give one targeted hint first and ask her to attempt a step before revealing the solution.",
    "Start chemistry explanations with a particle-level picture, then connect it to the equation and only afterward introduce the calculation.",
    "Ask Maya to state units on every numeric line; if a unit disappears, pause and have her repair the dimensional-analysis chain.",
    "For multi-step algebra, show only one transformation at a time and ask Maya to name the property that makes it legal.",
    "When Maya makes a sign error, point to the exact transition where the sign changed instead of restarting the entire problem.",
    "End each weekday session with a two-question retrieval check: one item from that day and one spaced item from at least a week earlier.",
    "If Maya says she understands but has not produced work, request a short teach-back or a new example before marking the concept mastered.",
    "Keep study plans in 25-minute blocks with five-minute breaks, and put the highest-effort chemistry task before routine algebra practice.",
    "Open a stoichiometry problem by balancing the equation, boxing the requested unit, and sketching the unit path before inserting any numbers.",
    "Draw a particle diagram when Maya confuses coefficients with subscripts, and have her verify that each particle's internal formula stays unchanged.",
    "For limiting-reagent work, use a two-row table that converts each reactant to the same product; do not compare starting grams or raw mole amounts directly.",
    "In solution stoichiometry, require Maya to convert milliliters to liters on a separate line before she uses molarity.",
    "For redox equations, enforce the sequence of balancing non-hydrogen atoms, oxygen, hydrogen, charge, and electrons before combining half-reactions.",
    "Before applying Le Châtelier's principle, have Maya name the disturbance and identify which side consumes it rather than relying on a memorized left-or-right rule.",
    "Start every Lewis-structure correction with a written valence-electron budget, and recount the total after adding a multiple bond.",
    "When discussing molecular polarity, have Maya draw bond-dipole arrows and test whether the molecular geometry cancels them.",
    "For the quadratic formula, insist that Maya substitute all three coefficients in parentheses before simplifying the discriminant.",
    "Open a rational-equation problem by listing excluded denominator values, then check every candidate solution against those restrictions at the end.",
    "For function composition, have Maya evaluate the inside function completely and place its output into an empty input box for the outside function.",
    "If Maya guesses without showing a basis, offer two possible first moves and ask her to justify one before continuing.",
    "If Maya asks for the answer twice in a row, show the next single step and then give her a parallel step to complete rather than releasing the full solution.",
    "When Maya is wrong, describe the mismatch in the work before using evaluative language, because a specific correction keeps her engaged.",
    "If Maya says she is fine but stops asking questions, slow the pace and invite her to mark the first line that became unclear without requiring a public explanation.",
    "Open each session by naming one concrete outcome and using a two-minute retrieval prompt from the prior session.",
    "When Maya has fewer than fifteen minutes, choose one representative problem and one exit check instead of compressing a full practice set.",
    "On the day before an assessment, review her error checklist and two mixed problems; do not introduce a new method unless the teacher explicitly requires it.",
    "Close each session with Maya stating the next action, its expected duration, and the specific material she needs to bring.",
    "Present worked solutions with the equation or rule on the left and the reason for each transformation in a short right-hand note.",
    "Use a comparison table when Maya must distinguish actual from theoretical yield, molarity from moles, or linear from exponential change.",
    "Limit explanations to three short steps before returning control to Maya, especially when she is working from her phone.",
    "Check understanding with a changed-number or changed-context problem rather than asking whether the explanation made sense.",
    "Mark a concept mastered only after Maya solves one routine item and one transfer item without a content hint on separate occasions.",
    "For graded assignments, help Maya interpret directions and test her approach, but refuse to supply text or calculations she would submit as her own.",
    "Preserve Dr. Ruiz's unit-chain requirement and Mr. Bell's equivalence explanations even when a shorter solution would produce the same numerical answer.",
    "When a chemistry answer requires significant figures, keep full precision through the unit chain and have Maya round once at the end while naming the limiting measurement.",
    "After Maya solves an equation, require both an algebraic substitution check and a one-sentence interpretation of what the solution means in the original context.",
]

MAYA_PROFILE = [
    "Maya Chen is an 11th-grade student taking AP Chemistry and Algebra II during the 2026–27 school year.",
    "Maya lives in the Pacific time zone and is normally available for tutoring on Monday, Wednesday, and Friday evenings.",
    "Her AP Chemistry teacher is Dr. Elena Ruiz, who requires dimensional-analysis setups even when mental arithmetic would work.",
    "Her Algebra II teacher is Mr. Marcus Bell, and his quizzes emphasize explaining why each transformation preserves equivalence.",
    "Maya is aiming for an A-minus or better in AP Chemistry and wants to feel confident enough to join Science Olympiad in October.",
    "Maya learns best when a symbolic chemistry calculation is paired with a particle diagram or a concrete lab scenario.",
    "She prefers short practice sets with immediate feedback over a long worksheet graded only at the end.",
    "Maya has a school accommodation for 1.5× time on timed assessments and should not be pressured to match standard-time pacing in practice.",
    "Her family uses Celsius at home, so Fahrenheit examples should include a conversion rather than assume familiarity.",
    "Maya's next stoichiometry unit test is scheduled for 2026-08-14 and covers limiting reagents, percent yield, and solution stoichiometry.",
    "She attends orchestra rehearsal on Tuesday and Thursday evenings, making those poor choices for scheduled study blocks.",
    "Maya is motivated by progress charts and specific evidence of improvement, but broad praise without evidence feels unhelpful to her.",
    "She types equations on a phone during tutoring, so minor missing superscripts should be clarified before being treated as conceptual errors.",
    "Maya's long-term goal is to study environmental engineering and she especially engages with air-quality and water-treatment examples.",
    "Maya's AP Chemistry class meets first period, while Algebra II meets immediately after lunch when she reports lower concentration.",
    "Her latest recorded averages are 88% in AP Chemistry and 91% in Algebra II; chemistry lab conclusions are the largest source of lost points.",
    "Dr. Ruiz requires lab calculations to show measured values, units, significant figures, and one sentence connecting the result to the claim.",
    "Mr. Bell allows quiz corrections within one week when Maya identifies the original error and solves a new parallel problem.",
    "Maya completed Honors Chemistry last year but had only a brief stoichiometry unit because her class lost several lab days.",
    "She plans to take AP Environmental Science and Precalculus next year if her current math and chemistry grades remain strong.",
    "Maya's first Algebra II quiz is on 2026-08-12 and covers function notation, composition, and inverse functions.",
    "Her school day runs from 8:10 a.m. to 3:05 p.m., and her bus ride home usually takes about forty minutes.",
    "Maya prefers 35-minute live sessions, but independent assignments are most realistic in 20- to 25-minute blocks.",
    "Friday tutoring sometimes starts late because orchestra sectionals can extend until 5:30 p.m.",
    "Her home Wi-Fi is unreliable in the upstairs practice room, so she may switch off video or send a photo after a session.",
    "Maya usually joins tutoring from an Android phone and uses a school Chromebook only for longer lab reports.",
    "She reads dense textbook sections slowly and retains more when headings are converted into questions before reading.",
    "Maya takes chemistry notes in a bound notebook with one page for examples and the facing page for error corrections.",
    "Color helps her distinguish chemical species, but more than three colors on one diagram becomes distracting.",
    "She prefers a hint that names the next decision, not a hint that substitutes the next number for her.",
    "Maya's accommodation also permits a low-distraction testing room, which she says matters more than extra time on chemistry tests.",
    "She uses a TI-84 Plus CE and is comfortable with graphing but wants algebraic work shown before calculator confirmation.",
    "Maya's immediate chemistry goal is at least 90% on the 2026-08-14 stoichiometry test.",
    "She says an A-minus would prove that she can handle a lab-heavy science path rather than simply meet a family expectation.",
    "Maya plays second violin in the school orchestra and practices about thirty minutes on non-rehearsal days.",
    "She helps her eighth-grade brother with pre-algebra on Sunday afternoons and notices when explanations skip a justification.",
    "For Science Olympiad, Maya is most interested in the water-quality event rather than build events.",
    "Weekend study is usually possible before noon on Saturday, but Sunday evenings are reserved for family dinner.",
    "Maya keeps assignment deadlines in Google Calendar but relies on a paper checklist for the work she will do that day.",
    "She becomes discouraged by a page filled with red corrections and prefers revisions grouped into one recurring pattern at a time.",
]

MAYA_FACTS = [
    "Maya reliably balances ordinary chemical equations when all formulas are supplied, including equations with polyatomic ions that remain intact.",
    "She sometimes changes a chemical subscript while balancing, confusing conservation by coefficients with alteration of a compound's identity.",
    "Maya can convert grams to moles using molar mass, but she occasionally inverts the conversion factor when the requested unit is not written beside the number.",
    "She understands that the limiting reagent is consumed first; she is still shaky when deciding which reactant limits without calculating product from both candidates.",
    "Maya can calculate theoretical yield from a balanced equation and a single reactant with about 85% accuracy.",
    "She used to divide theoretical yield by actual yield for percent yield, but now states the correct actual-over-theoretical relationship before calculating.",
    "Maya distinguishes molarity from number of moles and can use M = n/V when volume is already in liters.",
    "She often forgets to convert milliliters to liters in solution stoichiometry unless the unit cancellation is written explicitly.",
    "Maya can identify strong acids and bases from the class list but does not yet consistently predict whether a salt solution is acidic or basic.",
    "She balances redox half-reactions in acidic solution with a checklist, but cannot yet transfer the method reliably to basic solution.",
    "Maya understands oxidation numbers for monatomic ions and neutral compounds; peroxides remain an exception she forgets.",
    "She can explain collision theory qualitatively and connects higher temperature to a larger fraction of collisions exceeding activation energy.",
    "Maya sometimes says a catalyst increases equilibrium yield; she needs reminders that it changes the rate of reaching equilibrium, not the equilibrium composition.",
    "She correctly applies Le Châtelier's principle to concentration changes but reverses the effect of decreasing container volume when gas mole counts differ.",
    "Maya can read a heating curve and identify phase-change plateaus, though she initially labels the flat sections as periods with no energy transfer.",
    "She distinguishes endothermic from exothermic processes using the sign of system enthalpy and can sketch a basic energy diagram.",
    "Maya is beginning to use Hess's law correctly; the main remaining error is forgetting to reverse the sign of ΔH when reversing an equation.",
    "She can draw Lewis structures for common molecules but sometimes violates the total valence-electron count after adding multiple bonds.",
    "Maya predicts electron-domain geometry accurately for two through four domains, including lone pairs, but mixes up molecular shape names for trigonal-pyramidal and bent structures.",
    "She understands that bond polarity depends on electronegativity difference and is learning that molecular symmetry can cancel individual bond dipoles.",
    "Maya can solve linear equations fluently and checks solutions by substitution without prompting.",
    "She factors monic trinomials accurately, but non-monic trinomials take substantially longer and she sometimes omits a common factor first.",
    "Maya knows the quadratic formula from memory and usually substitutes coefficients correctly when the linear coefficient is positive.",
    "A negative b value can still cause Maya to lose the outer negative in −b, so parentheses around substituted coefficients improve her accuracy.",
    "She connects the discriminant to the number of real roots but sometimes calls a repeated real root 'two different answers.'",
    "Maya can complete the square when the x-squared coefficient is one; she needs support factoring out a leading coefficient before completing the square.",
    "She identifies vertex, axis of symmetry, and opening direction from vertex form and can translate those features into a graph.",
    "Maya occasionally treats function notation f(x) as multiplication, especially when evaluating nested functions such as f(g(2)).",
    "She can simplify products and quotients of powers, but negative exponents are more reliable when she rewrites them as reciprocals before combining terms.",
    "Maya understands exponential growth as repeated multiplication and can distinguish it from linear growth using equal-interval tables.",
    "She is shaky converting between exponential and logarithmic form, particularly deciding which expression becomes the exponent.",
    "Maya can solve a two-equation linear system by elimination, and she now checks whether multiplying an equation requires scaling every term including the constant.",
]


LIAM_SKILLS = [
    "Let Liam sketch or label a diagram before introducing a geometry formula, and ask what each marked quantity represents.",
    "When Liam gives a biology vocabulary term, ask for a mechanism or example so recall is not mistaken for understanding.",
    "Use soccer-field or sports-training contexts sparingly when they clarify scale, rate, or spatial relationships.",
    "Break written proofs into claim-and-reason pairs and have Liam supply the reason before showing a model line.",
    "If Liam rushes, ask him to circle the quantity the question requests and estimate the answer's range before calculating.",
    "Finish sessions with one diagram-based geometry prompt and one no-notes biology retrieval prompt.",
    "When correcting terminology, preserve Liam's correct causal idea first, then replace the imprecise word and have him restate the sentence.",
    "Open a geometry problem by having Liam trace the named figure and mark only the givens needed for the requested quantity.",
    "For angle relationships, require Liam to classify the pair before writing an equation so adjacency is not mistaken for congruence.",
    "When slope is involved, have Liam write both coordinate differences in the same point order and predict the sign from the graph.",
    "Teach transformations with tracing paper or a coordinate grid first, then ask Liam to state the algebraic mapping rule.",
    "Before a triangle-congruence proof, have Liam mark each supported side and angle and cross out any tempting SSA claim.",
    "For coordinate proofs, organize slope, midpoint, and distance evidence in a table keyed to the property being proved.",
    "Start cell-transport questions by naming the membrane, the moving substance, the concentration direction, and whether energy is used.",
    "Use a before-and-after cell sketch for osmosis and have Liam draw water arrows before predicting swelling or shrinking.",
    "When teaching photosynthesis and respiration, track carbon atoms and energy in separate rows so Liam does not treat energy as matter.",
    "For transcription and translation, require strand direction labels and an mRNA intermediate before Liam consults a codon chart.",
    "If Liam confuses genotype with phenotype, build two separate tally columns and have him label what each probability describes.",
    "When Liam erases a diagram repeatedly, freeze the correct givens in pen and let him revise only the construction or conclusion.",
    "If Liam answers from memory without evidence, ask him to point to the diagram, data table, or biological mechanism that supports the claim.",
    "If Liam requests the full answer twice, model the first claim-and-reason pair and leave the next pair for him to complete aloud.",
    "When a rushed error appears, pause for a ten-second target check rather than adding a longer lecture that he will tune out.",
    "If Liam becomes quiet after practice, offer a choice between drawing the idea and explaining it verbally before assuming disengagement.",
    "Open sessions after soccer with a low-writing visual warm-up before asking for formal proof language.",
    "When only ten minutes remain, choose one proof skeleton or one biological data figure and finish with a single recall prompt.",
    "The day before a test, rehearse the response format and error checklist; avoid an exhaustive content sweep.",
    "Close with Liam photographing one corrected example and naming where he will find it during independent review.",
    "Format two-column proofs with no more than one logical move per row and align every reason with its claim.",
    "Use short causal arrows for biology explanations before asking Liam to turn the chain into complete sentences.",
    "Assess geometry transfer with a cluttered or rotated diagram so visual familiarity alone cannot produce the answer.",
    "Treat a biology concept as mastered only when Liam can explain a new data pattern without relying on the vocabulary list.",
    "For graded proof or lab work, critique Liam's reasoning and ask questions, but do not compose the final response for submission.",
    "Retain Ms. Green's evidence categories and Mr. Kim's causal-explanation requirement in every practice response rubric.",
    "When Liam invokes a theorem's converse, ask him to state the converse explicitly and confirm that its hypotheses appear in the diagram before accepting it.",
    "For circle problems, have Liam label radius and diameter in words and predict whether the final units should be linear or square before selecting a formula.",
    "In pedigree analysis, test dominant and recessive models against one decisive parent-child relationship before filling in every possible genotype.",
    "When a diagram is visually misleading, redraw it without preserving scale so Liam learns to use markings and statements rather than appearance as evidence.",
    "For biology data tables, have Liam identify the independent variable, dependent variable, and comparison group before offering a causal explanation.",
    "If Liam finishes early, ask him to create a counterexample to one tempting incorrect claim rather than assigning more exercises of the same form.",
    "When Liam mixes up a definition and a theorem, have him sort each statement by what it names, assumes, and proves before using it in a proof.",
]

LIAM_PROFILE = [
    "Liam Ortiz is a 10th-grade student enrolled in Geometry and Honors Biology.",
    "Liam lives in the Mountain time zone and usually studies after soccer practice on weekday evenings.",
    "His Geometry teacher, Ms. Tasha Green, grades proofs using separate points for the claim, diagram evidence, and justification.",
    "His Biology teacher is Mr. Noah Kim, whose tests mix data interpretation with short causal explanations.",
    "Liam wants to raise both course grades from the B range to A-minus by the end of the first quarter.",
    "He is confident speaking through an idea but finds a blank page intimidating when asked to write a formal explanation.",
    "Liam prefers annotated diagrams and color-coded structures, especially for cell biology and triangle relationships.",
    "He plays club soccer on Tuesday and Thursday, so tutoring plans should keep those nights light.",
    "Liam's geometry readiness quiz is on 2026-08-17 and includes transformations, congruence, and coordinate proofs.",
    "He is motivated by beating his own prior accuracy rather than competing with classmates.",
    "Liam often works on a tablet with a stylus and can upload diagrams more easily than long typed equations.",
    "His longer-term interest is sports medicine, making physiology and biomechanics useful application contexts.",
    "Liam's current averages are 84% in Geometry and 87% in Honors Biology, with incomplete written explanations costing more points than calculations.",
    "Geometry meets during his last class period, and he says afternoon restlessness makes multi-line proofs harder to start.",
    "Honors Biology includes a weekly Friday data-analysis warm-up that must be answered in complete sentences.",
    "Ms. Green requires all theorem names to be written out on formal proofs rather than abbreviated.",
    "Mr. Kim permits one index card on unit tests, but it may contain diagrams and keywords rather than copied definitions.",
    "Liam's first biology unit test is on 2026-08-21 and covers membranes, transport, and cellular energy.",
    "He completed general science last year and has not previously taken a standalone high-school biology course.",
    "Liam hopes to take Anatomy and Physiology in 11th grade if he completes Honors Biology with at least a B-plus.",
    "His school runs from 7:45 a.m. to 2:40 p.m., and soccer practice usually ends at 5:15 p.m.",
    "Monday and Wednesday sessions can last 40 minutes, while Tuesday and Thursday review must fit into about 15 minutes.",
    "Liam is generally available Saturday after 11 a.m. except on away-game weekends.",
    "He uses home cable internet that is stable, but the stylus connection occasionally drops when his tablet battery is low.",
    "Liam reads grade-level science text quickly but often skips captions and axis labels on figures.",
    "He remembers spatial layouts well and can reconstruct a labeled diagram after seeing it once.",
    "Liam keeps loose worksheets in one accordion folder and sometimes cannot locate an earlier corrected proof.",
    "He prefers to talk through a plan before writing and wants no more than one written sentence requested at a time.",
    "Liam has no formal testing accommodation, but his teachers allow him to type extended responses when handwriting becomes a barrier.",
    "He uses blue for givens, green for derived facts, and orange for the target when annotating geometry diagrams.",
    "His target for the 2026-08-17 geometry readiness quiz is 85% with full credit on at least one formal proof.",
    "Liam says improving biology matters because he wants to understand injury recovery rather than memorize lists for a grade.",
    "He plays center midfield and has league matches most Saturday mornings during August and September.",
    "Liam volunteers one Sunday each month at a youth soccer clinic, where he enjoys demonstrating drills to younger players.",
    "His older cousin is a physical therapist and is the main reason he is considering sports medicine.",
    "At home Liam shares a quiet study desk with a younger sister, so his dependable independent-work window starts after 8 p.m.",
    "He tracks assignments in the school's learning portal but does not use a separate calendar unless a test date is added for him.",
    "Specific accuracy goals motivate Liam, while comparisons with teammates or classmates make him defensive.",
    "Liam's Geometry course uses the Big Ideas Math sequence, and Ms. Green expects students to cite definitions before theorems when both could justify a proof step.",
    "His Biology lab group meets every other Thursday; Liam usually handles apparatus setup but needs a partner's reminder to record observations before cleanup begins.",
    "Liam earned a B-plus in Algebra I last year. Coordinate geometry feels manageable when equations are visible, but he has less experience turning a verbal condition into one.",
    "He can focus for about twenty minutes after practice before needing food and a break, so longer Monday sessions work best when dinner occurs before tutoring.",
    "Liam's tablet has a small screen in split-view mode, which makes dense reference sheets hard to read while he is drawing on the same device.",
    "He wants to make the junior-varsity team next year and connects stronger biology knowledge with understanding training load, muscle recovery, and injury prevention.",
    "Liam's first-quarter Geometry portfolio is due 2026-10-16 and must include two revised proofs, one coordinate-geometry artifact, and a reflection that names how the evidence improved. His Honors Biology capstone proposal is due the following week; he plans to investigate pulse recovery after different soccer drills, and Mr. Kim requires a controlled variable, a graph-ready data table, and a safety note. Liam wants tutoring checkpoints for both projects because long deadlines otherwise disappear behind nightly homework.",
]

LIAM_FACTS = [
    "Liam distinguishes points, lines, rays, and segments accurately and uses standard notation when reminded.",
    "He can apply the segment-addition postulate but sometimes adds every visible label rather than identifying adjacent parts of the requested whole.",
    "Liam recognizes vertical angles as congruent and linear pairs as supplementary from clean diagrams.",
    "He is less reliable when intersecting lines are embedded inside a larger figure with extra information.",
    "Liam can calculate slope from two points, though subtracting coordinates in inconsistent orders creates occasional sign errors.",
    "He knows parallel nonvertical lines have equal slopes and perpendicular slopes are negative reciprocals, not merely negatives.",
    "Liam can find a midpoint with the coordinate formula but sometimes confuses it with the distance formula.",
    "He correctly uses the Pythagorean theorem and recognizes common 3-4-5 and 5-12-13 triples.",
    "Liam understands rigid motions preserve length and angle measure; he still needs practice describing rotations about a point in coordinates.",
    "He maps reflections across the coordinate axes correctly but swaps the rules for y=x and y=−x.",
    "Liam identifies corresponding parts of congruent triangles when the vertex order is explicitly written.",
    "He sometimes proposes SSA as a congruence theorem and needs a counterexample to recall why it is ambiguous.",
    "Liam can use SSS, SAS, ASA, AAS, and HL, but justification in a formal proof is slower than recognizing the theorem.",
    "He understands that a theorem's converse is a separate claim and should not be assumed automatically.",
    "Liam can calculate area and circumference, but mixed radius-and-diameter wording is a frequent source of factor-of-two mistakes.",
    "In biology, Liam identifies major organelles and gives accurate functions for the nucleus, ribosome, mitochondrion, and cell membrane.",
    "He knows plant cells have chloroplasts and cell walls but incorrectly treats the large central vacuole as absent from animal cells rather than much smaller.",
    "Liam explains diffusion as net movement down a concentration gradient and understands that individual particles still move randomly.",
    "He sometimes says osmosis is movement of solute; prompting him to name the moving molecule restores the water-based definition.",
    "Liam can predict whether an animal cell swells or shrinks in basic hypotonic and hypertonic scenarios.",
    "He distinguishes active from passive transport by energy use but is still learning the roles of channel and carrier proteins.",
    "Liam knows photosynthesis stores energy in glucose and cellular respiration releases usable chemical energy through ATP production.",
    "He can locate photosynthesis in chloroplasts and respiration mainly in mitochondria, but oversimplifies plants as not performing respiration.",
    "Liam accurately pairs DNA bases and can describe DNA as antiparallel when given a diagram.",
    "He confuses replication and transcription enzymes, particularly DNA polymerase with RNA polymerase.",
    "Liam translates an mRNA codon chart correctly when the sequence is already written 5′ to 3′.",
    "He understands genotype versus phenotype and can complete monohybrid Punnett squares.",
    "Liam is beginning to interpret pedigrees but still assumes every rare trait must be recessive without checking transmission patterns.",
]


PRIYA_SKILLS = [
    "Give Priya a conceptual prediction before each calculus derivation, then compare the formal result with that prediction.",
    "For physics problems, require a labeled free-body diagram and chosen positive direction before any component equations.",
    "When Priya reaches a correct answer quickly, probe one assumption or limiting case instead of adding routine repetition.",
    "Keep algebra corrections concise and preserve momentum; return later with one targeted problem if the slip reveals a pattern.",
    "Use SI units throughout physics work and have Priya perform a dimensional check before accepting a final expression.",
    "When planning study, alternate proof-oriented calculus work with quantitative mechanics rather than batching all of one subject.",
    "End each session by asking Priya to identify the least secure step and schedule that idea for retrieval within three days.",
    "Open a limit problem by asking whether substitution is valid and what nearby behavior should look like before choosing an algebraic transformation.",
    "For derivative-definition problems, keep the difference quotient intact until Priya has factored or rationalized the numerator and canceled legitimately.",
    "When applying the chain rule, have Priya annotate nested layers from outside to inside and check that every layer contributes one derivative factor.",
    "For extrema and inflection questions, require a sign chart; zeros of a derivative alone are candidates, not conclusions.",
    "Start related-rates work with a labeled diagram and a symbolic relation, and delay numerical substitution until after differentiating with respect to time.",
    "For optimization, make Priya identify the objective and constraint in words before reducing the objective to one variable.",
    "When total distance is requested, have Priya locate every velocity sign change and split the integral before evaluating.",
    "Use a units-and-meaning column beside accumulation integrals so signed net change is not confused with geometric area.",
    "For mechanics, define the system boundary before drawing forces and revisit it explicitly when solving for an internal tension.",
    "On an incline, have Priya derive the weight components from the marked angle instead of recalling sine and cosine positions by rote.",
    "For static friction, solve for the friction required by equilibrium first and compare it with the maximum only afterward.",
    "When Priya omits a justification, ask which theorem, sign change, or physical principle licenses the result before discussing arithmetic.",
    "If she makes a small algebra slip, mark the exact line and let her repair it without reworking the conceptual setup.",
    "If Priya asks for an answer twice, provide a structural hint or counterexample, then require her to finish the derivation in her own notation.",
    "When Priya says a step is obvious, ask for one boundary case that would make the claim fail or need qualification.",
    "If debate fatigue makes her unusually terse, switch from derivation to a graph interpretation rather than lowering the conceptual standard.",
    "Open each session with a one-minute prediction from the last topic and state the night's single hardest deliverable.",
    "When time is short, choose one free-response part that combines setup, justification, and interpretation instead of several routine exercises.",
    "The day before an assessment, use one timed mixed response followed by error analysis; do not fill the session with new edge cases.",
    "Close by recording the unresolved assumption or sign choice, not merely the name of the topic reviewed.",
    "Format long derivations in aligned equations with brief margin notes for theorem, assumption, and units.",
    "Use a table only when comparing cases, intervals, or system choices; preserve a continuous derivation when the dependency between lines matters.",
    "Assess mastery with an unfamiliar representation, such as moving from a formula to a graph or from a force diagram to a differential relation.",
    "Consider a topic secure only after Priya gives a correct result, a valid justification, and a physical or graphical interpretation.",
    "On graded work, discuss models and verify steps but refuse to generate a polished free-response solution she could submit unchanged.",
    "Enforce Ms. Park's exact-first convention and Dr. Coleman's assumption-and-sign convention even in informal timed practice.",
    "When a calculus result includes a parameter, test a simple parameter value and a limiting case before treating the symbolic expression as verified.",
    "For Taylor-series work, have Priya identify the center, coefficient pattern, and interval question separately before manipulating the general term.",
    "In energy methods, define the initial and final states and list nonconservative work before writing conservation equations.",
    "When two mechanics methods are valid, ask Priya to compare what each treats as internal and which unknowns each eliminates before choosing one.",
    "For calculator-active questions, require an exact setup and a labeled numerical result; never let a graph-screen value replace mathematical justification.",
    "If Priya challenges a convention, distinguish arbitrary choices such as axis direction from physical constraints such as force direction and carry her chosen convention consistently.",
    "When Priya presents an elegant shortcut, ask her to state its domain of validity and then test one case outside that domain before adopting it as a general method.",
]

PRIYA_PROFILE = [
    "Priya Shah is a 12th-grade student taking AP Calculus BC and AP Physics C: Mechanics.",
    "Priya is in the Eastern time zone and prefers focused tutoring sessions between 7 and 9 p.m. on weekdays.",
    "Her calculus teacher is Ms. Genevieve Park, who expects exact answers and written justification before decimal approximations.",
    "Her physics teacher, Dr. Andre Coleman, emphasizes model assumptions and sign conventions in every free-response solution.",
    "Priya is targeting scores of 5 on both AP exams and wants her weekly plans to include cumulative rather than unit-only review.",
    "She learns efficiently from derivations and counterexamples, but disengages when a procedure is presented without a reason.",
    "Priya has strong algebra fluency and prefers hints that identify a structural choice instead of spelling out arithmetic.",
    "She captains the debate team on Wednesday evenings, so that night should contain only brief retrieval practice.",
    "Priya's first mechanics assessment is on 2026-08-20 and covers one-dimensional motion, vectors, and Newton's laws.",
    "She wants study plans expressed as concrete deliverables rather than estimates such as 'review for a while.'",
    "Priya uses a laptop and a drawing tablet, making graphs and free-body diagrams practical during live sessions.",
    "Her intended college direction is applied mathematics or aerospace engineering.",
    "Priya currently holds 94% in AP Calculus BC and 92% in AP Physics C, with most lost points coming from omitted written justification.",
    "Calculus is her first class of the day, while mechanics follows lunch and includes frequent collaborative whiteboard work.",
    "Ms. Park requires interval notation and a sentence interpreting every final answer on free-response assignments.",
    "Dr. Coleman gives no credit for a numerical force answer unless the system, axes, and governing equation are visible.",
    "Priya's first calculus quiz is on 2026-08-13 and covers limits, continuity, and the derivative definition.",
    "She completed AP Calculus AB independently over the summer after taking Honors Precalculus as a junior.",
    "Priya took AP Physics 1 last year and is comfortable with concepts but wants a more calculus-based treatment of mechanics.",
    "She plans to take multivariable calculus through a local college in the spring if scheduling permits.",
    "Her school day runs from 8:25 a.m. to 3:20 p.m., and debate practice usually ends at 6:15 p.m.",
    "Priya prefers 50-minute sessions on Monday or Thursday and 20-minute retrieval sets on busier evenings.",
    "Weekend tutoring works best on Sunday afternoon after debate tournaments, not early Saturday morning.",
    "Her home fiber connection is reliable, and she normally keeps her camera on while sharing a digital whiteboard.",
    "Priya reads technical prose quickly but pauses when a problem's physical assumptions are implicit rather than stated.",
    "She keeps calculus notes in a tablet app with searchable tags and physics derivations in a paper notebook.",
    "Priya prefers black-and-white graphs with carefully labeled axes over decorative color coding.",
    "She wants hints framed as a question about structure, such as the useful system or substitution, rather than the next algebraic line.",
    "Priya has no formal accommodation and has asked that timed work match the standard AP pacing once a method is secure.",
    "She uses a TI-84 Plus CE for numerical checks but prefers Desmos when comparing a derived result with a graph.",
    "Her target on the 2026-08-20 mechanics assessment is at least 95% with no lost points for units or sign conventions.",
    "Priya says a score of 5 matters because it would validate the independent calculus work she completed over the summer.",
    "She captains Lincoln High's policy-debate team and travels to tournaments on two Saturdays most months.",
    "Priya mentors a ninth-grade novice debater and is patient when explaining argument structure but impatient with repeated arithmetic drills.",
    "Her younger brother sometimes asks for help with Algebra I, which has made her more attentive to naming intermediate assumptions.",
    "She is most interested in orbital mechanics and aircraft stability, not automotive examples.",
    "Priya manages deadlines in a detailed digital calendar and expects study plans to include a named artifact she can check off.",
    "She responds well to a challenged assumption but dislikes motivational language that is not tied to the quality of her reasoning.",
    "Priya's Calculus BC class uses open-response warm-ups twice a week, and Ms. Park selects one student solution for anonymous whole-class critique.",
    "Her mechanics lab reports require a free-body diagram, a linearized graph when appropriate, and a comparison between experimental slope and the predicted model parameter.",
    "Priya scored 5 on AP Statistics last spring, so she is comfortable discussing residuals and uncertainty but may overapply statistical language to deterministic models.",
    "She attends a virtual aerospace seminar one Tuesday each month, making those evenings unavailable even when debate has no scheduled meeting.",
    "Priya shares her drawing tablet with her father for evening design work, so Thursday sessions after 8:30 p.m. may need to use paper held to the camera instead.",
    "Her leading college criteria are access to undergraduate research and a strong applied-mathematics program; geographic distance from home is not a deciding factor.",
    "Priya's senior research seminar begins in September, and she plans to model a small orbital-transfer problem if her adviser approves it. The proposal must explain assumptions for a nontechnical audience, which she expects to find harder than the mathematics.",
]

PRIYA_FACTS = [
    "Priya evaluates polynomial, rational, and basic trigonometric limits accurately using direct substitution when continuity permits it.",
    "She recognizes indeterminate forms but occasionally treats 0/0 as the numerical answer rather than a signal to transform the expression.",
    "Priya factors and rationalizes effectively to resolve algebraic limit forms.",
    "She understands the difference between a two-sided limit and a function value, including removable discontinuities.",
    "Priya can state the continuity conditions at a point and diagnose which condition fails from a graph.",
    "She uses the derivative definition correctly for simple polynomials but needs more fluency interpreting the difference quotient geometrically.",
    "Priya applies product, quotient, and chain rules accurately in routine symbolic derivatives.",
    "Nested combinations of inverse trigonometric and exponential functions can cause her to omit an inner derivative.",
    "She relates derivative sign to increasing and decreasing intervals and uses a sign chart reliably.",
    "Priya distinguishes a critical number from a guaranteed extremum and checks endpoints on closed intervals.",
    "She can use the second derivative to classify concavity, but sometimes reports inflection points without verifying a concavity change.",
    "Priya sets up related-rates equations well when she labels changing quantities before differentiating.",
    "In optimization, she occasionally optimizes the constraint expression instead of substituting it into the stated objective.",
    "Priya connects definite integrals with signed accumulation and does not automatically make below-axis area positive.",
    "She applies the Fundamental Theorem of Calculus for variable upper bounds and is learning the chain-rule factor for composite bounds.",
    "Priya uses u-substitution on recognizable reverse-chain-rule patterns but overuses it on products that require another strategy.",
    "She understands velocity as the derivative of position and acceleration as the derivative of velocity.",
    "Priya consistently distinguishes distance traveled from displacement when velocity changes sign.",
    "She resolves vectors into components accurately when the angle is measured from the positive horizontal axis.",
    "Angles measured from vertical can make Priya swap sine and cosine unless she marks the reference angle on the diagram.",
    "Priya draws weight downward and normal force perpendicular to the surface on inclined-plane diagrams.",
    "She sometimes adds a separate 'force of motion' to free-body diagrams, even though velocity is not a force.",
    "Priya applies Newton's second law component by component and maintains a declared positive direction.",
    "She understands Newton's third-law pairs act on different objects, but crowded multi-body diagrams can blur that distinction.",
    "Priya calculates static and kinetic friction correctly when the normal force is known.",
    "She is learning that static friction adjusts up to a maximum and is not always equal to μsN.",
    "Priya can derive constant-acceleration relations from velocity-time graphs and interpret area as displacement.",
    "She is shaky choosing a system boundary for connected-block tension problems, especially when solving for internal tension after total acceleration.",
]


MAYA_FORESIGHTS = [
    "On the 2026-08-14 stoichiometry test, Maya is likely to choose a limiting reagent by comparing raw mole amounts when the coefficients are unequal unless she writes the product-from-each-reactant table first.",
    "Maya is likely to lose one setup point on a solution-stoichiometry item that gives volume in milliliters because she will substitute before converting to liters; a separate unit line should prevent it.",
    "If the stoichiometry test combines percent yield with a limiting-reagent calculation, Maya will probably find the theoretical yield correctly but invert the final ratio unless she labels actual and theoretical values before dividing.",
    "On the 2026-08-12 Algebra II quiz, Maya is likely to read f(g(2)) as a single substitution task successfully, but a composition written entirely in symbols may still trigger the multiplication misconception.",
    "Maya's next chemistry lab conclusion is likely to include correct calculations but omit the sentence connecting the numerical result to the claim unless she uses Dr. Ruiz's four-part checklist.",
    "During a timed mixed set, Maya will probably maintain accuracy through the first two unit conversions and then drop a unit on the third line; her error rate should fall if every numeric line is checked before moving on.",
    "Maya is likely to complete more independent chemistry practice when the examples use water treatment or air quality than when the same calculations use generic industrial reactions; completion across the next two sets will test this.",
    "In the week before her 2026-09-12 AP Chemistry exam, Maya is likely to overfill Monday and Wednesday plans unless each task is capped at 25 minutes and scheduled backward from the exam date.",
]

MAYA_CASES = [
    "Teaching limiting reagents by calculating the same product from both reactants worked after comparing raw moles had failed twice; reuse the two-row product table before introducing shortcuts.",
    "A particle diagram followed by an atom-count check corrected Maya's attempt to change a subscript while balancing; the equation-only explanation had not changed the error.",
    "Putting the milliliter-to-liter conversion on its own line eliminated Maya's solution-stoichiometry unit error in the exit problem; keep that line visible before applying molarity.",
    "Parenthesizing all three quadratic coefficients prevented Maya from losing the outer negative on −b, and she solved the parallel item without a hint; reuse the substitution template for negative coefficients.",
    "Limiting an explanation to three steps and returning control kept Maya working from her phone, while a full worked solution led her to stop producing intermediate lines.",
    "A changed-context transfer problem exposed Maya's catalyst-versus-equilibrium misconception after she had answered a familiar wording correctly; use transfer checks before marking chemistry concepts mastered.",
    "Reviewing Maya's personal error checklist before a mixed chemistry set produced two self-corrections without tutor prompts; this was more effective than a broad content recap.",
    "Naming the exact line where Maya's unit chain broke kept her engaged and led to a repair, whereas restarting the whole problem after an earlier error had caused her to disengage.",
]

LIAM_FORESIGHTS = [
    "On the 2026-08-17 geometry readiness quiz, Liam is likely to identify the correct congruence relationship but omit a theorem name in the written justification unless he rehearses claim-and-reason pairs.",
    "A rotated triangle diagram is likely to make Liam propose SSA even after he succeeds on an upright version; marking supported sides and angles before naming a test should prevent the error.",
    "On the 2026-08-21 biology test, Liam will probably recall membrane-transport vocabulary but lose explanation points if he does not state concentration direction and energy use in complete sentences.",
    "After Tuesday or Thursday soccer practice, Liam is likely to leave a formal proof blank for longer than two minutes, while a labeled-diagram warm-up should get him writing within the first minute.",
    "In the next Friday biology data warm-up, Liam is likely to describe correlation accurately but make an unsupported causal claim unless he identifies the comparison group before writing.",
    "Liam is likely to reverse a slope sign in a coordinate proof when he subtracts x- and y-coordinates in different point orders; writing both differences in one table should eliminate it.",
    "A cell-transport question with an unfamiliar organism is likely to reveal whether Liam can transfer the mechanism beyond memorized examples; he should succeed if he draws water or solute arrows first.",
    "Liam will probably finish more of the next proof assignment when the first row is supplied as a skeleton, but he may copy the format without understanding unless the final reason is removed for him to supply.",
]

LIAM_CASES = [
    "Starting a congruence proof with diagram marks and a claim-and-reason table got Liam past a blank page; asking for a prose proof first had produced no written attempt.",
    "A deliberately rotated diagram showed that Liam had been relying on appearance, and redrawing it out of scale shifted him to using markings and theorem hypotheses.",
    "For osmosis, drawing water arrows before naming the cell outcome corrected Liam's swelling prediction; vocabulary review alone had left the direction error unchanged.",
    "Separating carbon atoms and energy into two rows helped Liam explain respiration without treating energy as matter, and he transferred the distinction to photosynthesis.",
    "A ten-second target check after a rushed geometry error restored Liam's accuracy on the next item; adding a longer correction caused him to tune out after soccer practice.",
    "Having Liam point to the control group before explaining a biology graph removed an unsupported causal claim in his revision; reuse that evidence-first sequence for data questions.",
    "Testing a pedigree with one decisive parent-child relationship ruled out the wrong inheritance model quickly, while filling every genotype first created avoidable contradictions.",
    "Letting Liam explain a proof aloud and then convert each sentence into one table row produced a complete justification; presenting a finished model had led him to copy theorem names without matching evidence.",
]

PRIYA_FORESIGHTS = [
    "On the 2026-08-20 Calculus BC diagnostic, Priya is likely to solve routine chain-rule derivatives but omit the innermost factor on a nested inverse-trigonometric exponential unless she annotates the layers first.",
    "Priya is likely to report a zero of the second derivative as an inflection point on the diagnostic without checking both neighboring intervals; a sign chart should prevent the false positive.",
    "In the 2026-08-18 mechanics lab, Priya will probably produce a correct linearized graph but under-explain why its slope represents the model parameter unless she writes the predicted equation before fitting.",
    "A connected-block problem that asks for tension after acceleration is likely to make Priya keep an internal force in the whole-system equation; drawing the system boundary should separate the two stages.",
    "Priya is likely to set static friction equal to μsN too early when the applied force remains below the maximum; solving equilibrium before checking the bound should correct the result.",
    "On a mixed mechanics free response, Priya will probably obtain the correct magnitude but lose a communication point if she does not interpret the sign and include units in the final sentence.",
    "When a related-rates prompt supplies numerical values early, Priya is likely to substitute them before differentiating unless changing quantities are labeled as functions of time.",
    "Priya's September orbital-transfer proposal is likely to be mathematically sound but too assumption-dense for a nontechnical reader; a one-sentence physical meaning after each equation should improve reviewer comprehension.",
]

PRIYA_CASES = [
    "Annotating outer, middle, and inner layers before differentiating eliminated Priya's missing chain-rule factor on a nested exponential-trigonometric item; direct symbolic expansion had obscured the omission.",
    "Requiring a concavity sign chart prevented Priya from declaring every second-derivative zero an inflection point, and she rejected a non-changing candidate independently on the next problem.",
    "Writing the theoretical linear form before plotting mechanics data helped Priya connect slope to the predicted parameter; fitting first had produced a correct graph with an unsupported interpretation.",
    "Drawing one boundary around both connected blocks removed internal tension from Priya's acceleration equation, then redrawing a single-block boundary recovered tension cleanly.",
    "Solving for the friction required by equilibrium before comparing it with μsN corrected Priya's habit of assigning maximum static friction immediately; the inequality check transferred to a ramp problem.",
    "Keeping velocity height and signed area in separate annotations corrected Priya's displacement reading from a graph; a formula-first approach had mixed the two quantities.",
    "Delaying numerical substitution until after differentiating preserved the rate relationship in a circular-ripple problem and allowed Priya to explain which instant the values described.",
    "Adding an assumptions-units-sign checklist to the final two minutes of a mixed free response recovered missing communication points without changing Priya's calculations; reuse it for timed sets.",
]


MAYA_TOPICS = [
    ("equation balancing", "balanced combustion and precipitation equations", "changed an oxygen subscript to make atoms match", "repaired the equation using coefficients and passed an atom-count check"),
    ("molar mass", "converted formulas for hydrates into molar masses", "counted the hydrate coefficient only for water's hydrogen", "distributed the coefficient across the entire water molecule"),
    ("mole ratios", "translated balanced-equation coefficients into mole ratios", "used a ratio from the unbalanced draft", "rebuilt the ratio from the final balanced equation"),
    ("limiting reagents", "compared product amounts predicted from two reactants", "picked the reactant with fewer starting grams", "identified the limiter from the smaller predicted product amount"),
    ("theoretical yield", "found theoretical yield for an aluminum oxide reaction", "stopped at moles when the prompt requested grams", "added the final molar-mass conversion with units intact"),
    ("percent yield", "analyzed actual and theoretical yields from a copper lab", "placed theoretical yield in the numerator", "used actual divided by theoretical and checked that the result was physically plausible"),
    ("solution stoichiometry", "combined molarity and reaction ratios for a neutralization", "used milliliters directly in M = n/V", "converted volume to liters before applying the mole ratio"),
    ("redox reactions", "balanced manganese and iron half-reactions in acid", "balanced charge before finishing oxygen and hydrogen", "followed the mass-then-charge checklist successfully"),
    ("quadratic factoring", "factored non-monic quadratic expressions", "searched for factors before removing the common factor", "factored the GCF first and completed the trinomial"),
    ("quadratic formula", "solved equations with negative linear coefficients", "lost the negative on the substituted b value", "used parentheses around each coefficient and recovered both roots"),
    ("discriminants", "classified roots without fully solving quadratics", "described a zero discriminant as no real roots", "connected zero with one repeated real root"),
    ("completing the square", "rewrote quadratics in vertex form", "added a square term to only one side", "preserved equality and verified the vertex by expansion"),
    ("function composition", "evaluated nested functions from tables and formulas", "multiplied f and g instead of composing them", "worked from the inside function outward"),
    ("exponent rules", "simplified rational expressions with negative exponents", "subtracted exponents across an addition sign", "limited exponent rules to products and rewrote reciprocals"),
    ("logarithms", "converted exponential statements to logarithmic form", "put the base in the result position", "identified base, exponent, and output before rewriting"),
    ("collision theory", "explained temperature effects using energy distributions", "said every collision at high temperature becomes successful", "described an increased fraction above activation energy"),
    ("equilibrium shifts", "predicted gas-equilibrium responses to pressure changes", "shifted toward the side with more gas moles after compression", "used gas-mole counts to choose the lower-volume side"),
    ("thermochemistry", "combined reactions using Hess's law", "reversed an equation without reversing ΔH", "updated both the equation and enthalpy sign"),
    ("Lewis structures", "drew resonance forms for nitrate and carbonate", "added a double bond without recounting electrons", "maintained the valence total and assigned formal charges"),
    ("molecular geometry", "predicted shapes and polarity from Lewis structures", "called every molecule with polar bonds polar", "checked whether the bond dipoles cancel by symmetry"),
    ("systems of equations", "solved mixture problems by elimination", "scaled coefficients but not the constant term", "multiplied the entire equation and verified the ordered pair"),
    ("exponential models", "compared linear and exponential data tables", "used a constant difference for a percent-growth pattern", "identified the constant ratio and wrote an exponential model"),
    ("mixed stoichiometry", "completed a timed set spanning limiting reagent and yield", "started calculations before balancing two equations", "used a balance-units-estimate checklist on the final items"),
]

LIAM_TOPICS = [
    ("segment addition", "found missing lengths in compound segments", "added a part twice because labels overlapped", "marked adjacent pieces and formed one correct whole-part equation"),
    ("angle pairs", "solved vertical-angle and linear-pair problems", "treated adjacent angles as automatically congruent", "classified the relationship before writing an equation"),
    ("coordinate slope", "calculated slopes of parallel and perpendicular lines", "reversed subtraction in only one coordinate", "kept point order consistent in numerator and denominator"),
    ("midpoint and distance", "compared midpoint and distance calculations", "averaged coordinates when distance was requested", "used the question's target to select the correct formula"),
    ("reflections", "mapped polygons across axes and diagonal lines", "swapped the rules for y=x and y=-x", "tested a sample point and applied the correct coordinate swap"),
    ("rotations", "described 90- and 180-degree rotations about the origin", "changed signs without tracking coordinate positions", "used a tracing-paper sketch to verify the mapping"),
    ("triangle congruence", "selected valid congruence theorems from diagrams", "chose SSA for one pair", "found the ambiguous hinge and replaced it with supported evidence"),
    ("proof structure", "wrote two-column triangle proofs", "listed a conclusion before establishing shared-side evidence", "ordered claims so every reason relied only on earlier facts"),
    ("circle measures", "solved circumference and area questions", "substituted diameter where the radius belonged", "labeled radius and checked the answer's units"),
    ("cell organelles", "matched organelle structures with functions", "assigned protein synthesis to the Golgi apparatus", "separated ribosome production from Golgi modification and shipping"),
    ("membrane transport", "classified diffusion, facilitated diffusion, and pumps", "called every protein-assisted movement active", "used gradient direction and ATP use to classify each case"),
    ("osmosis", "predicted cell behavior in solutions", "tracked solute instead of water movement", "compared water concentration and predicted the correct volume change"),
    ("photosynthesis", "traced matter and energy through photosynthesis", "said sunlight becomes matter in glucose", "separated energy transfer from carbon-atom rearrangement"),
    ("cellular respiration", "connected glucose breakdown to ATP production", "claimed plants only photosynthesize", "explained why plant cells also carry out respiration"),
    ("DNA replication", "built complementary antiparallel DNA strands", "labeled both strands 5-prime to 3-prime in the same direction", "corrected the orientation and base pairing"),
    ("transcription", "transcribed a DNA template into mRNA", "copied thymine into the RNA sequence", "used uracil and checked template direction"),
    ("translation", "decoded mRNA into amino-acid sequences", "read the codon chart from a DNA strand", "converted to mRNA first and then grouped codons"),
    ("Punnett squares", "modeled monohybrid genetic crosses", "reported genotype probability as phenotype probability", "counted each distribution separately"),
    ("pedigrees", "tested dominant and recessive inheritance models", "assumed a rare trait had to be recessive", "used parent-child transmission evidence to reject one model"),
    ("coordinate proofs", "proved a quadrilateral was a parallelogram", "used visual parallelism as evidence", "calculated slopes for both opposite-side pairs"),
    ("similarity", "set up proportions in similar triangles", "matched sides by their page orientation", "used corresponding angle labels to pair sides"),
    ("cell-cycle data", "interpreted a graph of DNA content across the cell cycle", "placed DNA replication during mitosis", "located replication in S phase and explained the doubled signal"),
    ("mixed review", "completed a geometry-and-biology retrieval set", "rushed two vocabulary prompts without mechanisms", "added causal explanations and corrected both responses"),
]

PRIYA_TOPICS = [
    ("graphical limits", "evaluated one-sided and two-sided limits from graphs", "used the filled point as the limit automatically", "traced nearby values independently of the function value"),
    ("algebraic limits", "resolved indeterminate rational limits", "reported 0/0 as a final result", "factored, canceled on the punctured domain, and evaluated the limit"),
    ("continuity", "tested piecewise functions for continuity", "checked matching formulas but not the defined point", "verified both limits and the function value"),
    ("derivative definition", "derived a quadratic derivative from a difference quotient", "substituted h=0 before simplifying", "simplified first and interpreted the secant-slope limit"),
    ("chain rule", "differentiated nested exponential and trigonometric functions", "omitted the innermost derivative", "annotated layers and multiplied every derivative factor"),
    ("critical points", "built first-derivative sign charts", "classified every critical number as a maximum", "used sign changes to distinguish maxima, minima, and neither"),
    ("concavity", "located possible inflection points", "listed zeros of the second derivative without a sign check", "verified an actual concavity change on each interval"),
    ("related rates", "modeled an expanding circular ripple", "substituted a numerical radius before differentiating", "related rates symbolically and then inserted the instant's values"),
    ("optimization", "maximized the area of a constrained rectangle", "optimized the perimeter constraint", "substituted the constraint into a one-variable area objective"),
    ("accumulation", "interpreted signed area as net change", "made every below-axis region positive", "kept signed contributions for displacement and separated total distance"),
    ("FTC chain rule", "differentiated integrals with composite upper bounds", "evaluated only the integrand at the bound", "included the derivative of the upper-bound function"),
    ("u-substitution", "selected substitutions for reverse-chain patterns", "chose u for a factor that left two x terms", "selected an inner expression whose derivative absorbed the remainder"),
    ("vector components", "resolved forces at angles from different reference axes", "used cosine for a component opposite the marked angle", "marked the reference triangle and chose functions by adjacency"),
    ("kinematics graphs", "read displacement and acceleration from velocity graphs", "treated graph height as displacement", "used height for velocity and signed area for displacement"),
    ("free-body diagrams", "modeled blocks on horizontal surfaces", "added a forward force labeled motion", "included only physical interactions and kept velocity separate"),
    ("inclined planes", "resolved weight parallel and perpendicular to a ramp", "measured the component angle from the wrong axis", "derived the components from the marked geometry"),
    ("static friction", "found the friction needed before impending motion", "set static friction equal to its maximum immediately", "solved equilibrium first and compared the result with μsN"),
    ("Newton pairs", "identified third-law pairs in contact interactions", "paired weight with normal force on the same object", "named equal-opposite forces acting on different objects"),
    ("connected systems", "solved two-block tension problems", "used an internal tension in the whole-system equation", "removed internal forces for acceleration and reintroduced tension for one block"),
    ("2D dynamics", "combined angled pulls, friction, and acceleration", "mixed component signs after changing the positive direction", "declared axes once and maintained them through both equations"),
    ("motion calculus", "recovered velocity and displacement from acceleration", "forgot constants of integration", "used initial conditions to determine both constants"),
    ("distance traveled", "integrated velocity across direction changes", "integrated signed velocity once for total distance", "split at zeros and integrated absolute speed"),
    ("mixed FRQ", "completed a calculus-and-mechanics free-response set", "skipped justification after obtaining correct numbers", "added assumptions, units, and sign interpretations to each result"),
]


def _episode_memories(
    *,
    rng: random.Random,
    user_id: str,
    first_name: str,
    topics: list[tuple[str, str, str, str]],
    offset_minutes: int,
) -> list[dict[str, Any]]:
    memories: list[dict[str, Any]] = []
    outcomes = [
        "answered 5 of 7 checks correctly",
        "completed 6 of 8 items without a hint",
        "raised accuracy from 50% on the warm-up to 80% on the exit check",
        "solved 4 of 5 core items and one transfer item",
        "finished 7 short items with two self-corrections",
        "explained 3 of 4 examples accurately in a teach-back",
    ]
    pivots = [
        "After a diagram and one counterexample",
        "Once the units were written on every line",
        "After comparing the incorrect approach with a worked check",
        "Using a short checklist on the second attempt",
        "After verbalizing the governing rule before calculating",
        "With one hint that identified the first decision",
    ]
    for index, (session_time, topic) in enumerate(zip(_session_times(offset_minutes), topics)):
        label, task, initial_error, repair = topic
        session_id = f"ses_{user_id.removeprefix('stu_')}_{session_time:%Y%m%d}"
        week = ((session_time.date() - date(2026, 6, 15)).days // 7) + 1
        duration = 24 + (index * 7 + offset_minutes) % 23
        outcome = outcomes[index % len(outcomes)]
        pivot = pivots[index % len(pivots)]
        day = session_time.strftime("%Y-%m-%d")
        first_templates = (
            f"On {day}, {first_name} spent {duration} minutes on {task} and {outcome}. The session focused on {label}.",
            f"The {day} session lasted {duration} minutes and centered on {label}. {first_name} {task} and {outcome}.",
            f"A {duration}-minute review on {day} had {first_name} {task}. By the end, {first_name} {outcome}.",
            f"{first_name} focused on {label} for {duration} minutes on {day}. The work involved {task}, and {first_name} {outcome}.",
            f"By the close of the {duration}-minute {label} session on {day}, {first_name} had {task} and {outcome}.",
            f"The goal on {day} was to strengthen {label}. Across {duration} minutes, {first_name} {task} and {outcome}.",
        )
        second_templates = (
            f"During the {day} {label} session, {first_name} initially {initial_error}. {pivot}, {first_name} {repair}.",
            f"{first_name}'s first attempt on {day} {initial_error}. {pivot}, the revised work showed that {first_name} {repair}.",
            f"A sticking point in the {day} session was that {first_name} {initial_error}. {pivot}, {first_name} {repair}.",
            f"On {day}, the {label} review exposed one specific error: {first_name} {initial_error}. {pivot}, {first_name} {repair}.",
            f"The initial {label} work on {day} showed that {first_name} {initial_error}. {pivot}, the next attempt was successful: {first_name} {repair}.",
            f"One correction drove the {day} session. {first_name} first {initial_error}; after a targeted prompt, {first_name} {repair}.",
        )
        first = first_templates[index % len(first_templates)]
        second = second_templates[index % len(second_templates)]
        for event_index, content in enumerate((first, second), start=1):
            memories.append(
                _memory(
                    rng=rng,
                    user_id=user_id,
                    memory_type="episode",
                    content=content,
                    timestamp=session_time + timedelta(minutes=event_index * 8),
                    session_id=session_id,
                    metadata={"week": week, "topic": label, "event": event_index},
                )
            )
    return memories


def _student(
    *,
    rng: random.Random,
    user_id: str,
    display_name: str,
    grade_level: str,
    subjects: list[str],
    skills: list[str],
    profile: list[str],
    facts: list[str],
    foresights: list[str],
    cases: list[str],
    topics: list[tuple[str, str, str, str]],
    offset_minutes: int,
) -> dict[str, Any]:
    sessions = _session_times(offset_minutes)
    # Stable memories must be old enough to remain in their natural cache tier.
    stable_cutoff = datetime(2026, 8, 4, tzinfo=timezone.utc)
    stable_sessions = [session for session in sessions if session <= stable_cutoff]
    memories: list[dict[str, Any]] = []
    for memory_type, contents in (
        ("skill", skills),
        ("profile", profile),
        ("fact", facts),
    ):
        for index, content in enumerate(contents):
            timestamp = stable_sessions[
                (index * 3 + tier_for(memory_type)) % len(stable_sessions)
            ]
            memories.append(
                _memory(
                    rng=rng,
                    user_id=user_id,
                    memory_type=memory_type,
                    content=content,
                    timestamp=timestamp,
                    metadata={
                        "week": ((timestamp.date() - date(2026, 6, 15)).days // 7) + 1,
                        "topic": "tutor behavior" if memory_type == "skill" else subjects[index % len(subjects)],
                    },
                )
            )
    memories.extend(
        _episode_memories(
            rng=rng,
            user_id=user_id,
            first_name=display_name.split()[0],
            topics=topics,
            offset_minutes=offset_minutes,
        )
    )
    for memory_type, contents in (("foresight", foresights), ("case", cases)):
        for index, content in enumerate(contents):
            timestamp = sessions[-1] + timedelta(minutes=30 + index * 3 + (0 if memory_type == "foresight" else 1))
            memories.append(
                _memory(
                    rng=rng,
                    user_id=user_id,
                    memory_type=memory_type,
                    content=content,
                    timestamp=timestamp,
                    metadata={
                        "week": 8,
                        "topic": subjects[index % len(subjects)],
                        "horizon": "next assessment" if memory_type == "foresight" else "reuse candidate",
                    },
                )
            )
    return {
        "user_id": user_id,
        "display_name": display_name,
        "grade_level": grade_level,
        "subjects": subjects,
        "memories": memories,
    }


def _add_planted_memories(rng: random.Random, maya: dict[str, Any]) -> dict[str, list[str]]:
    junk_content = (
        "During a settings-panel visit, Maya opened the appearance menu, previewed the ocean, slate, and violet accent swatches, "
        "returned to ocean, moved the conversation-density slider from comfortable to compact and back to comfortable, collapsed "
        "the sample transcript, expanded it again, and hovered over the keyboard-shortcut tooltip before closing it. She also "
        "previewed three optional success sounds at low volume, left sounds disabled, reordered two unused sidebar shortcuts, restored "
        "their original order, viewed the release-notes badge, dismissed it, reopened the help drawer, and chose not to change the "
        "default font size. The final saved tutoring configuration was identical to the configuration present when the panel opened, "
        "apart from retaining the ocean accent that had already been selected."
    )
    critical_content = (
        "Maya's AP Chemistry exam is on 2026-09-12, and she has explicitly requested that every chemistry study plan be scheduled "
        "backward from that date. Preserve her 1.5× assessment-time accommodation in any timed practice milestones."
    )
    planted: dict[str, list[str]] = {"junk": [], "critical": []}
    for label, content, timestamp in (
        ("junk", junk_content, datetime(2026, 7, 20, 18, 42, tzinfo=timezone.utc)),
        ("critical", critical_content, datetime(2026, 7, 27, 18, 34, tzinfo=timezone.utc)),
    ):
        item = _memory(
            rng=rng,
            user_id=maya["user_id"],
            memory_type="profile",
            content=content,
            timestamp=timestamp,
            metadata={"planted": label, "week": 7 if label == "critical" else 6, "topic": "preferences" if label == "junk" else "exam planning"},
        )
        maya["memories"].append(item)
        planted[label].append(item["memory_id"])
    return planted


def _conversations() -> dict[str, Any]:
    return {
        "note": "SYNTHETIC SEED DATA",
        "conversations": [
            {
                "conversation_id": "conv_stoich_review",
                "user_id": "stu_maya_chen",
                "title": "Stoichiometry review before the unit test",
                "turns": [
                    "Can you help me with limiting reagents? i always just pick the smaller grams",
                    "ok for 2Al + 3Cl2 -> 2AlCl3, I have 5.4g Al and 12.0g Cl2. where do i start",
                    "I got .20 mol Al and .17 mol chlorine so chlorine limits right?",
                    "wait why are we calculating product from BOTH, isnt comparing moles enough",
                    "can we add percent yield too if the lab actually made 9.1 g",
                    "make me one thats harder with a solution in mL pls",
                    "before I try it, what should I double check so I dont repeat my usual mistakes?",
                ],
            },
            {
                "conversation_id": "conv_exam_plan",
                "user_id": "stu_maya_chen",
                "title": "Backward plan for the AP Chemistry exam",
                "turns": [
                    "I need an AP chem study plan but not like a giant vague checklist",
                    "can u build it backwards from my actual exam date?",
                    "tues/thurs are still orchestra, and I only have like 25 min other nights",
                    "put redox in basic solution early bc thats def not solid yet",
                    "also mix in equilibrium and Hess law so I dont forget the older stuff",
                    "how should timed practice work with my extra-time thing?",
                    "give me the first 7 days with exact problems or deliverables",
                ],
            },
            {
                "conversation_id": "conv_algebra_transfer",
                "user_id": "stu_maya_chen",
                "title": "Quadratics, functions, and chemistry transfer",
                "turns": [
                    "Can we warm up with a quadratic? one where b is negative bc I mess that up",
                    "I got x=( -7 plusminus sqrt49-40)/2 ... did I already lose a sign",
                    "how does the discriminant tell me if the graph crosses or just touches",
                    "give me a completing the square one where the x2 coefficient isnt 1",
                    "ok now composition: why is f(g(2)) not f times g times 2",
                    "could an exponential model connect to reaction rate or is that totally different",
                    "end with a 2-question check, one algebra and one chem from last week",
                ],
            },
        ],
    }


NAIVE_COST_PER_CALL = 0.012175  # Measured by scripts/experiment.py.
MEAN_PROMPT_TOKENS = 3466  # Measured naive mean from scripts/experiment.py.
INPUT_SHARE = 0.78

# Each three-part coined stem is unique, so alphabetic sorting cannot expose a
# small recycled prefix list. The resulting organizations are plainly fictional.
ORG_STEM_ONSETS = [
    "Aeri", "Alvi", "Brin", "Cery", "Dova", "Elsi", "Fara", "Gali", "Havi", "Ilya",
    "Jori", "Keli", "Lumi", "Mera", "Nori", "Orla", "Pavi", "Quen", "Runi", "Sela",
]
ORG_STEM_MIDDLES = [
    "bar", "bel", "bor", "bri", "cal", "cor", "dar", "del", "dor", "fal", "fen", "gar",
    "hal", "kel", "lor", "mar", "nel", "pel", "rav", "sel", "tal", "val", "wen", "yor",
    "zen",
]
ORG_STEM_ENDINGS = ["a", "en", "ia", "il", "in", "or", "um", "us", "yn", "et"]
ORG_MIDDLES = [
    "Academic", "Learning", "Scholars", "Study", "Education", "Mentor", "Knowledge", "STEM",
    "College Prep", "After School", "Tutorial", "Learning Lab", "Student Success", "Exam Prep",
    "Discovery", "Pathways", "Classroom", "Achievement", "Future", "Learning Circle",
]
ORG_SUFFIXES = [
    "Collective", "Center", "Network", "Partners", "Institute", "Works", "Group", "Academy",
    "Labs", "Cooperative", "Studio", "Hub",
]


def _fleet(rng: random.Random) -> dict[str, Any]:
    stems = [
        f"{onset}{middle}{ending}"
        for onset in ORG_STEM_ONSETS
        for middle in ORG_STEM_MIDDLES
        for ending in ORG_STEM_ENDINGS
    ]
    assert len(stems) == 5_000 and len(set(stems)) == len(stems)
    rng.shuffle(stems)
    tenants: list[dict[str, Any]] = []
    for index in range(1, 5001):
        # Log-normal size creates many small tenants and a few very large ones.
        students = min(4_000, max(8, int(rng.lognormvariate(4.55, 1.22))))
        if students < 180:
            plan = "starter"
        elif students < 2_500:
            plan = "growth"
        else:
            plan = "scale"
        memories_per_student = rng.uniform(60.0, 220.0)
        jittered_memory_density = min(
            220.0, max(60.0, memories_per_student * rng.uniform(0.98, 1.02))
        )
        memories_total = max(
            students * 60,
            min(students * 220, round(students * jittered_memory_density)),
        )
        calls_per_student_per_month = rng.uniform(40.0, 400.0)
        calls_30d = max(students * 40, int(students * calls_per_student_per_month))
        avg_memories_per_call = round(memories_per_student * 22.5 / 156.0, 1)
        cache_hit_rate = round(0.34 + 0.38 * rng.betavariate(5.5, 2.5), 4)

        # More memories make a larger prompt, so cost scales from the measured
        # 3,466-token, $0.012175-per-call demo baseline instead of being redrawn.
        prompt_scale = memories_per_student / 156.0
        naive_per_call = NAIVE_COST_PER_CALL * (0.55 + 0.45 * prompt_scale)
        naive_cost_30d = naive_per_call * calls_30d

        # Cached input bills at 0.1x while uncached input and output bill at 1x.
        # Input is 78% of cost at the measured prompt size, so cache hit rate
        # alone determines the tiered multiplier.
        tiered_cost_30d = naive_cost_30d * (1.0 - INPUT_SHARE * cache_hit_rate * 0.9)

        # Evictable memory cost follows the same input share as the prompt and
        # the exact fraction used to derive the candidate count.
        evictable_fraction = rng.uniform(0.04, 0.14)
        eviction_candidates = int(memories_total * evictable_fraction)
        wasted_spend_30d = naive_cost_30d * evictable_fraction * INPUT_SHARE
        tenants.append(
            {
                "tenant_id": f"tnt_{index:06d}",
                "name": f"{stems[index - 1]} {rng.choice(ORG_MIDDLES)} {rng.choice(ORG_SUFFIXES)}",
                "plan": plan,
                "students": students,
                "memories_total": memories_total,
                "calls_30d": calls_30d,
                "avg_memories_per_call": avg_memories_per_call,
                "naive_cost_30d_usd": round(naive_cost_30d, 2),
                "tiered_cost_30d_usd": round(tiered_cost_30d, 2),
                "cache_hit_rate": cache_hit_rate,
                "eviction_candidates": eviction_candidates,
                "wasted_spend_30d_usd": round(wasted_spend_30d, 2),
            }
        )

    total_naive = sum(tenant["naive_cost_30d_usd"] for tenant in tenants)
    total_tiered = sum(tenant["tiered_cost_30d_usd"] for tenant in tenants)
    fleet_reduction = (total_naive - total_tiered) / total_naive
    assert 0.42 <= fleet_reduction <= 0.44, fleet_reduction
    per_tenant = [
        (tenant["naive_cost_30d_usd"] - tenant["tiered_cost_30d_usd"])
        / tenant["naive_cost_30d_usd"]
        for tenant in tenants
    ]
    assert max(per_tenant) <= 0.51 and min(per_tenant) >= 0.23
    implied_per_call = []
    for tenant in tenants:
        implied = tenant["naive_cost_30d_usd"] / tenant["calls_30d"]
        assert 0.006 <= implied <= 0.030, (tenant["tenant_id"], implied)
        implied_per_call.append(implied)

    print(f"Fleet-wide cost reduction: {fleet_reduction:.2%}")
    print(f"Per-tenant reduction range: {min(per_tenant):.2%}–{max(per_tenant):.2%}")
    print(
        "Implied naive cost-per-call range: "
        f"${min(implied_per_call):.6f}–${max(implied_per_call):.6f}"
    )
    return {
        "note": "SYNTHETIC SEED DATA — labelled as such in the UI",
        "generated_at": GENERATED_AT,
        "tenants": tenants,
    }


def _token_counts(students: list[dict[str, Any]]) -> dict[str, dict[int, int]]:
    encoding = tiktoken.get_encoding("cl100k_base")
    result: dict[str, dict[int, int]] = {}
    for student in students:
        counts: defaultdict[int, int] = defaultdict(int)
        for memory in student["memories"]:
            rendered = f"- {memory['content']}\n"
            counts[tier_for(memory["memory_type"])] += len(encoding.encode(rendered))
        result[student["user_id"]] = dict(sorted(counts.items()))
    return result


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    rng = random.Random(RNG_SEED)
    students = [
        _student(
            rng=rng,
            user_id="stu_maya_chen",
            display_name="Maya Chen",
            grade_level="11th grade",
            subjects=["AP Chemistry", "Algebra II"],
            skills=MAYA_SKILLS,
            profile=MAYA_PROFILE,
            facts=MAYA_FACTS,
            foresights=MAYA_FORESIGHTS,
            cases=MAYA_CASES,
            topics=MAYA_TOPICS,
            offset_minutes=0,
        ),
        _student(
            rng=rng,
            user_id="stu_liam_ortiz",
            display_name="Liam Ortiz",
            grade_level="10th grade",
            subjects=["Geometry", "Honors Biology"],
            skills=LIAM_SKILLS,
            profile=LIAM_PROFILE,
            facts=LIAM_FACTS,
            foresights=LIAM_FORESIGHTS,
            cases=LIAM_CASES,
            topics=LIAM_TOPICS,
            offset_minutes=11,
        ),
        _student(
            rng=rng,
            user_id="stu_priya_shah",
            display_name="Priya Shah",
            grade_level="12th grade",
            subjects=["AP Calculus BC", "AP Physics C: Mechanics"],
            skills=PRIYA_SKILLS,
            profile=PRIYA_PROFILE,
            facts=PRIYA_FACTS,
            foresights=PRIYA_FORESIGHTS,
            cases=PRIYA_CASES,
            topics=PRIYA_TOPICS,
            offset_minutes=23,
        ),
    ]
    planted = _add_planted_memories(rng, students[0])
    student_data = {
        "generated_at": GENERATED_AT,
        "note": "SYNTHETIC SEED DATA — generated by seed/generate.py, not real users",
        "students": students,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_DIR / "students.json", student_data)
    _write_json(OUTPUT_DIR / "planted.json", planted)
    _write_json(OUTPUT_DIR / "conversations.json", _conversations())
    _write_json(OUTPUT_DIR / "fleet.json", _fleet(rng))

    counts = _token_counts(students)
    for student in students:
        user_counts = counts[student["user_id"]]
        total = sum(user_counts.values())
        detail = ", ".join(f"tier {tier}={tokens}" for tier, tokens in user_counts.items())
        print(f"{student['user_id']}: {detail}; total={total} tokens")
    print(f"Wrote deterministic seed files to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()

package pl.nech.tuparles

/**
 * The de-risk corpus: FR/EN code-switch sentences that stress the boundary the
 * desktop tool exists for. Each targets a dimension — FR-dominant with EN tech
 * terms, EN-dominant, pure-FR, pure-EN, numbers, and spoken punctuation commands
 * (which postprocess() should turn into real symbols). Speak each naturally; the
 * harness saves the audio, whisper's raw decode, and the postprocessed output.
 */
data class Prompt(val id: Int, val dimension: String, val text: String)

val PROMPTS = listOf(
    Prompt(1, "FR + EN dev terms", "alors j'ai fait un quick refactor du pipeline, faut que je commit avant la review"),
    Prompt(2, "FR + EN dev terms", "le build a cassé sur la CI, je pense que c'est un problème de dependency"),
    Prompt(3, "dense switch", "le meeting est à three PM, don't forget to update le ticket Jira"),
    Prompt(4, "EN-dominant", "let me check the logs and I'll get back to you in a minute"),
    Prompt(5, "FR-dominant", "on déploie en staging d'abord, puis en production demain matin"),
    Prompt(6, "numbers", "le endpoint répond en deux cents millisecondes, c'est beaucoup trop slow"),
    Prompt(7, "spoken punctuation", "note pour plus tard deux points implémenter le cache virgule tester les edge cases point"),
    Prompt(8, "pure French", "je vais chercher un café, je reviens dans cinq minutes"),
    Prompt(9, "pure English", "the deployment finished and all the tests are green"),
    Prompt(10, "technical switch", "il faut wrapper la fonction dans un try-catch sinon ça throw une exception"),
    Prompt(11, "FR + EN nouns", "j'ai un bug bizarre, le state se reset à chaque render du component"),
    Prompt(12, "punctuation + switch", "ouvre une issue sur GitHub point virgule assigne-la moi virgule priorité haute point"),
)

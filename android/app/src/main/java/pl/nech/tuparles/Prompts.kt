package pl.nech.tuparles

/**
 * The de-risk corpus: FR/EN code-switch the way bilingual people actually talk —
 * across music, cooking, gaming, sport, film, street culture, not just dev. Each
 * embeds English loanwords in French speech (the boundary the tool exists for).
 * Speak each naturally; the harness saves the audio, whisper's raw decode, and
 * the postprocessed output. #14 tests spoken punctuation becoming real symbols.
 */
data class Prompt(val id: Int, val dimension: String, val text: String)

val PROMPTS = listOf(
    Prompt(1, "beatmaking", "j'ai bouclé le beat mais le snare sonne trop sec, faut que je rajoute un peu de reverb sur le drop"),
    Prompt(2, "rap / flow", "franchement sa punchline sur le dernier bar était fire, le flow est super clean"),
    Prompt(3, "DJ / electronic", "le BPM est à cent vingt-huit, je vais layer un pad avant le breakdown"),
    Prompt(4, "cuisine", "tu fais revenir les oignons, ensuite tu deglaze avec un peu de soy sauce"),
    Prompt(5, "gaming", "il m'a clutch le round en un contre trois, son aim est complètement insane"),
    Prompt(6, "fitness", "aujourd'hui c'est leg day, quatre sets de squats et après un peu de stretching"),
    Prompt(7, "cinéma", "le plot twist était un peu predictable mais le casting rattrape tout le film"),
    Prompt(8, "mode / street", "j'adore ton fit, le oversize avec les sneakers vintage ça match trop bien"),
    Prompt(9, "danse", "on bosse le footwork sur le break, et tu gardes le focus sur les freezes"),
    Prompt(10, "émotions / casual", "j'étais grave overwhelmed cette semaine, j'avais juste besoin de décompresser un peu"),
    Prompt(11, "skate", "j'ai enfin land mon kickflip, par contre le grind sur le rail je galère encore"),
    Prompt(12, "science", "on a run l'experiment trois fois mais les results sont pas vraiment significatifs"),
    Prompt(13, "voyage", "le check-in est à trois heures, on pose les bags et on part explorer la ville"),
    Prompt(14, "ponctuation parlée", "note pour le mix deux points monter les basses virgule baisser un peu les mids point"),
    Prompt(15, "dessin / art", "j'ai fini le sketch, maintenant je passe au lineart avant de commencer à color"),
)

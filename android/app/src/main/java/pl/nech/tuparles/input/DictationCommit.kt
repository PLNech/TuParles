package pl.nech.tuparles.input

/** The result a keyboard gets back from ACTION_RECOGNIZE_SPEECH. */
fun recognizeSpeechResult(text: String): ArrayList<String>? {
    val trimmed = text.trim()
    if (trimmed.isEmpty()) return null
    return arrayListOf(trimmed)
}

/** Hands dictated text to whoever owns the cursor. Empty text is a no-op. */
fun commitDictation(commit: (String) -> Unit, text: String): Boolean {
    val trimmed = text.trim()
    if (trimmed.isEmpty()) return false
    commit(trimmed)
    return true
}

package pl.nech.tuparles.data

import androidx.room.TypeConverter

/** Room <-> enum bridge for [TranscriptState] (stored as its name, TEXT). */
class Converters {
    @TypeConverter
    fun toTranscriptState(name: String?): TranscriptState =
        name?.let { runCatching { TranscriptState.valueOf(it) }.getOrNull() } ?: TranscriptState.NONE

    @TypeConverter
    fun fromTranscriptState(state: TranscriptState): String = state.name
}

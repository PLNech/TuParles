package pl.nech.tuparles.di

import android.content.Context
import androidx.room.Room
import dagger.Binds
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import pl.nech.tuparles.core.NotesRepository
import pl.nech.tuparles.core.RecorderSession
import pl.nech.tuparles.core.TranscriptionEngine
import pl.nech.tuparles.core.WhisperTranscriptionEngine
import pl.nech.tuparles.data.AppDatabase
import pl.nech.tuparles.data.MIGRATION_1_2
import pl.nech.tuparles.data.NoteDao
import pl.nech.tuparles.data.RoomNotesRepository
import pl.nech.tuparles.record.AudioRecorderSession
import javax.inject.Singleton

/** Provides the Room stack. */
@Module
@InstallIn(SingletonComponent::class)
object DataModule {
    @Provides
    @Singleton
    fun database(@ApplicationContext ctx: Context): AppDatabase =
        Room.databaseBuilder(ctx, AppDatabase::class.java, AppDatabase.NAME)
            .addMigrations(MIGRATION_1_2)
            .build()

    @Provides
    fun noteDao(db: AppDatabase): NoteDao = db.noteDao()

    /** Process-lived scope for work that must outlive any screen (see [ApplicationScope]). */
    @Provides
    @Singleton
    @ApplicationScope
    fun applicationScope(): CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
}

/** Binds the core contracts to their Android implementations. */
@Module
@InstallIn(SingletonComponent::class)
abstract class BindsModule {
    @Binds
    @Singleton
    abstract fun notesRepository(impl: RoomNotesRepository): NotesRepository

    @Binds
    abstract fun recorderSession(impl: AudioRecorderSession): RecorderSession

    // Phase B: the vendored whisper.cpp engine. It self-reports [available] = false
    // when no model asset is bundled, so the app degrades to Phase A (audio-only)
    // without any wiring change — no need for the NoopTranscriptionEngine binding.
    @Binds
    @Singleton
    abstract fun transcriptionEngine(impl: WhisperTranscriptionEngine): TranscriptionEngine
}

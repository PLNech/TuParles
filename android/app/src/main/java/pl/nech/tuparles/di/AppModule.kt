package pl.nech.tuparles.di

import android.content.Context
import androidx.room.Room
import dagger.Binds
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import pl.nech.tuparles.core.NoopTranscriptionEngine
import pl.nech.tuparles.core.NotesRepository
import pl.nech.tuparles.core.RecorderSession
import pl.nech.tuparles.core.TranscriptionEngine
import pl.nech.tuparles.data.AppDatabase
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
        Room.databaseBuilder(ctx, AppDatabase::class.java, AppDatabase.NAME).build()

    @Provides
    fun noteDao(db: AppDatabase): NoteDao = db.noteDao()
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

    @Binds
    @Singleton
    abstract fun transcriptionEngine(impl: NoopTranscriptionEngine): TranscriptionEngine
}

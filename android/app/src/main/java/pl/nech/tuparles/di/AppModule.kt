package pl.nech.tuparles.di

import android.content.Context
import androidx.room.Room
import dagger.Binds
import dagger.Lazy
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
import pl.nech.tuparles.data.MIGRATION_2_3
import pl.nech.tuparles.data.MIGRATION_3_4
import pl.nech.tuparles.data.NoteDao
import pl.nech.tuparles.data.RoomNotesRepository
import pl.nech.tuparles.model.DownloadManagerFileDownloader
import pl.nech.tuparles.model.FileDownloader
import pl.nech.tuparles.model.ModelCatalog
import pl.nech.tuparles.model.ModelManager
import pl.nech.tuparles.model.ModelPreferences
import pl.nech.tuparles.model.ModelResolver
import pl.nech.tuparles.model.ModelStore
import pl.nech.tuparles.model.PendingWork
import pl.nech.tuparles.model.SharedPrefsModelPreferences
import pl.nech.tuparles.record.AudioRecorderSession
import pl.nech.tuparles.transcribe.TranscriptionManager
import java.io.File
import javax.inject.Singleton

/** Provides the Room stack. */
@Module
@InstallIn(SingletonComponent::class)
object DataModule {
    @Provides
    @Singleton
    fun database(@ApplicationContext ctx: Context): AppDatabase =
        Room.databaseBuilder(ctx, AppDatabase::class.java, AppDatabase.NAME)
            .addMigrations(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4)
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
    // when no model is resolvable (lean APK, download not finished), so the app degrades
    // to record-only without any wiring change — no NoopTranscriptionEngine needed.
    @Binds
    @Singleton
    abstract fun transcriptionEngine(impl: WhisperTranscriptionEngine): TranscriptionEngine

    @Binds
    @Singleton
    abstract fun modelPreferences(impl: SharedPrefsModelPreferences): ModelPreferences

    @Binds
    @Singleton
    abstract fun fileDownloader(impl: DownloadManagerFileDownloader): FileDownloader

    /** The model manager is also what the engine reads to resolve its weights. */
    @Binds
    @Singleton
    abstract fun modelResolver(impl: ModelManager): ModelResolver

    /** Wakes model-waiting notes once a download lands (injected lazily to break the cycle). */
    @Binds
    @Singleton
    abstract fun pendingWork(impl: TranscriptionManager): PendingWork
}

/** The model download/storage subsystem (#13, app-weight goal). */
@Module
@InstallIn(SingletonComponent::class)
object ModelModule {

    @Provides
    @Singleton
    fun modelStore(@ApplicationContext ctx: Context): ModelStore =
        ModelStore(File(ctx.filesDir, "models"))

    @Provides
    @Singleton
    fun modelManager(
        @ApplicationContext ctx: Context,
        store: ModelStore,
        downloader: FileDownloader,
        prefs: ModelPreferences,
        @ApplicationScope scope: CoroutineScope,
        pending: Lazy<PendingWork>,
    ): ModelManager = ModelManager(
        store = store,
        downloader = downloader,
        prefs = prefs,
        scope = scope,
        bundledAssetPresent = bundledAssetPresent(ctx),
        pending = pending,
    )

    /** Whether this build shipped the dev asset (see [ModelCatalog.BUNDLED_ASSET_PATH]). */
    private fun bundledAssetPresent(ctx: Context): Boolean = runCatching {
        ctx.assets.open(ModelCatalog.BUNDLED_ASSET_PATH).close()
        true
    }.getOrDefault(false)
}

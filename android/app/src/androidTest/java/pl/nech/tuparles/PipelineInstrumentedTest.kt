package pl.nech.tuparles

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.BeforeClass
import org.junit.Test
import org.junit.runner.RunWith

/**
 * On-device proof that the core pipeline actually works on this build — the wiring
 * the keyboard, scratchpad, widget, and recognizer all sit on. It exercises the three
 * heavy seams end-to-end on the real device: the embedded-CPython postprocess module,
 * the whisper.cpp model load, and a full Dictation.decode (whisper JNI → postprocess,
 * including the threads param). It asserts the plumbing, not transcription quality
 * (silence in → a well-formed Take out): a regression in any seam fails here, fast.
 */
@RunWith(AndroidJUnit4::class)
class PipelineInstrumentedTest {

    companion object {
        private val ctx = InstrumentationRegistry.getInstrumentation().targetContext

        @BeforeClass @JvmStatic
        fun bootstrap() {
            if (!Python.isStarted()) Python.start(AndroidPlatform(ctx))
            runBlocking { Models.ensureLoaded(ctx) }
        }
    }

    @Test fun postprocessModuleLoadsAndRuns() {
        val py = Python.getInstance().getModule("tuparles.pipeline")
        val out = py.callAttr("postprocess", "ceci est un test").toString()
        assertNotNull(out)
        assertTrue("postprocess should return non-empty for non-empty input", out.isNotEmpty())
    }

    @Test fun modelLoadsAndEngineReady() {
        assertTrue("Engine should be ready after ensureLoaded", Engine.ready)
        assertTrue("loadedFrom should name the model", Engine.loadedFrom.isNotEmpty())
    }

    @Test fun decodePipelineEndToEnd() {
        // 1s of silence: non-empty so it actually runs whisper + postprocess + the
        // threads param, proving the wiring without depending on a speech fixture.
        val silent = ShortArray(SAMPLE_RATE)
        val take = runBlocking { Dictation.decode(silent, "fr", postprocessOn = true, threads = 0) }
        assertEquals("take carries the loaded model", Engine.loadedFrom, take.model)
        assertEquals("lang echoed back", "fr", take.lang)
        assertTrue("decode time recorded", take.ms >= 0)
        assertNotNull("clean text is never null", take.clean)
        assertTrue("audio length ~1s", take.seconds in 0.9f..1.1f)
    }
}

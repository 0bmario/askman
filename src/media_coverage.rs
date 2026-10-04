#[derive(Clone, Debug)]
struct MediaRequest {
    action: &'static str,
    object_type: Option<&'static str>,
    scope: Option<&'static str>,
    output_form: Option<&'static str>,
    modifiers: Vec<&'static str>,
    output_format: Option<&'static str>,
}

fn has(query: &str, phrase: &str) -> bool {
    format!(" {query} ").contains(&format!(" {phrase} "))
}

fn normalized(query: &str) -> String {
    let words: Vec<_> = query
        .to_ascii_lowercase()
        .split(|c: char| !c.is_ascii_alphanumeric() && c != '_' && c != '.')
        .filter(|word| !word.is_empty())
        .map(str::to_owned)
        .collect();
    words.join(" ")
}

// Recognize only the media vocabulary validated by the frozen experiment.
fn parse_media_request(query: &str) -> Option<MediaRequest> {
    let query = normalized(
        query.trim_end_matches(|character: char| matches!(character, '.' | '!' | '?' | ';' | ':')),
    );
    let is_speech = ["speak", "speech", "spoken", "read aloud", "say aloud"]
        .iter()
        .any(|cue| has(&query, cue));
    let is_capture = [
        "screenshot",
        "screenshots",
        "screen recording",
        "record the screen",
        "record the mac screen",
        "still image",
        "capture the screen",
        "capture the whole display",
        "capture one named application window",
        "capture a rectangular area",
        "capture an interactive rectangular area",
    ]
    .iter()
    .any(|cue| has(&query, cue))
        || (has(&query, "screen") && has(&query, "record"))
        || (has(&query, "record") && has(&query, "video") && has(&query, "region"));
    let is_speech = is_speech || (has(&query, "synthesize") && has(&query, "mp3"));
    if is_speech == is_capture {
        return None;
    }

    if is_speech {
        if has(&query, "list available") && has(&query, "voices") {
            return Some(MediaRequest {
                action: "list",
                object_type: Some("voice"),
                scope: Some("available_voices"),
                output_form: Some("terminal_text"),
                modifiers: Vec::new(),
                output_format: None,
            });
        }
        if has(&query, "save the spoken audio simultaneously")
            || has(&query, "saving the spoken audio simultaneously")
        {
            return Some(MediaRequest {
                action: "speak_and_save",
                object_type: Some("file_contents"),
                scope: None,
                output_form: Some("audio_file"),
                modifiers: vec!["simultaneous_playback_and_save"],
                output_format: None,
            });
        }

        let creates_file = has(&query, "audio file") || has(&query, "aiff") || has(&query, "mp3");
        let action = if creates_file {
            "create_audio_file"
        } else {
            "speak"
        };
        let object_type = if creates_file {
            Some("spoken_text")
        } else if has(&query, "file") {
            Some("file_contents")
        } else if has(&query, "phrase") || has(&query, "sentence") || has(&query, "message") {
            Some("phrase")
        } else {
            return None;
        };
        let mut modifiers = Vec::new();
        if has(&query, "polish") {
            modifiers.push("polish_voice");
        }
        if has(&query, "chosen voice") || has(&query, "custom voice") {
            modifiers.push("custom_voice");
        }
        if has(&query, "words per minute") || has(&query, "speech rate") {
            modifiers.push("custom_rate");
        }
        if has(&query, "selected lines") {
            modifiers.push("selected_lines");
        }
        if has(&query, "pause speech") || has(&query, "pause midway") {
            modifiers.push("pause_mid_sentence");
        }
        if has(&query, "output device") || has(&query, "audio output device") {
            modifiers.push("audio_output_device");
        }
        if has(&query, "repeatedly") || has(&query, "repeat") {
            modifiers.push("repeat_until_process_finishes");
        }
        if creates_file {
            modifiers.push("save_spoken_text");
        }
        let output_format = if has(&query, "aiff") {
            Some("aiff")
        } else if has(&query, "mp3") {
            Some("mp3")
        } else {
            None
        };
        return Some(MediaRequest {
            action,
            object_type,
            scope: if object_type == Some("file_contents") {
                Some("specified_file")
            } else {
                None
            },
            output_form: Some(if creates_file {
                "audio_file"
            } else {
                "audio_playback"
            }),
            modifiers,
            output_format,
        });
    }

    let is_video = has(&query, "record") || has(&query, "screen recording");
    let action = if is_video {
        "capture_video"
    } else {
        "capture_still"
    };
    let mut object_type = Some("screen");
    let mut scope = Some("screen");
    let mut output_form = if is_video { "video_file" } else { "image_file" };
    let mut modifiers = Vec::new();
    let mut output_format = None;

    if has(&query, "interactive rectangular area") || has(&query, "rectangular area") {
        object_type = Some("screen_region");
        scope = Some("selected_rectangular_area");
        modifiers.push("interactive_selection");
    }
    if has(&query, "selected region") || has(&query, "selected rectangular region") {
        object_type = Some("screen_region");
        scope = Some("selected_rectangular_area");
    }
    if has(&query, "include the pointer") || has(&query, "include the cursor") {
        modifiers.push("include_cursor");
    }
    if has(&query, "wait") && has(&query, "seconds") {
        modifiers.push("delay_seconds");
    }
    if has(&query, "preview") {
        output_form = "preview_app";
        modifiers.push("open_in_preview");
    }
    if has(&query, "clipboard") {
        output_form = "clipboard";
    }
    if has(&query, "microphone") {
        modifiers.push("microphone_audio");
    }
    if has(&query, "every second") || has(&query, "every 1 second") {
        modifiers.push("repeated_interval");
    }
    if has(&query, "named application window") || has(&query, "named window") {
        object_type = Some("application_window");
        scope = Some("named_application_window");
        modifiers.push("target_named_window");
    }
    if has(&query, "quality setting") {
        modifiers.push("jpeg_quality");
    }
    if has(&query, "png") || query.contains(".png") {
        output_format = Some("png");
    } else if has(&query, "jpeg") || has(&query, "jpg") {
        output_format = Some("jpeg");
    }

    Some(MediaRequest {
        action,
        object_type,
        scope,
        output_form: Some(output_form),
        modifiers,
        output_format,
    })
}

struct MediaExample {
    action: &'static str,
    object_type: &'static str,
    scope: &'static str,
    output_form: &'static str,
    modifiers: &'static [&'static str],
    unknown_slots: &'static [&'static str],
    command: &'static str,
    description: &'static str,
}

// Approved tldr-pages revision e1cb966e711d73c42d75e79834be7e4dc17264ef.
// A single example must cover all recognized clauses; examples cannot combine.
const MEDIA_EXAMPLES: &[MediaExample] = &[
    // pages/osx/say.md:8
    MediaExample {
        action: "speak",
        object_type: "phrase",
        scope: "unknown",
        output_form: "audio_playback",
        modifiers: &[],
        unknown_slots: &["scope"],
        command: "say \"{{I like to ride my bike.}}\"",
        description: "Say a phrase aloud:",
    },
    // pages/osx/say.md:12
    MediaExample {
        action: "speak",
        object_type: "file_contents",
        scope: "specified_file",
        output_form: "audio_playback",
        modifiers: &[],
        unknown_slots: &[],
        command: "say --input-file {{filename.txt}}",
        description: "Read a file aloud:",
    },
    // pages/osx/say.md:16
    MediaExample {
        action: "speak",
        object_type: "phrase",
        scope: "unknown",
        output_form: "audio_playback",
        modifiers: &["custom_voice", "custom_rate"],
        unknown_slots: &["scope"],
        command: "say --voice {{voice}} --rate {{words_per_minute}} \"{{I'm sorry Dave, I can't let you do that.}}\"",
        description: "Say a phrase with a custom voice and speech rate:",
    },
    // pages/osx/say.md:20
    MediaExample {
        action: "list",
        object_type: "voice",
        scope: "available_voices",
        output_form: "terminal_text",
        modifiers: &[],
        unknown_slots: &[],
        command: "say --voice \"?\"",
        description: "List the available voices (different voices speak in different languages):",
    },
    // pages/osx/say.md:24
    MediaExample {
        action: "speak",
        object_type: "phrase",
        scope: "unknown",
        output_form: "audio_playback",
        modifiers: &["polish_voice"],
        unknown_slots: &["scope"],
        command: "say --voice {{Zosia}} \"{{Litwo, ojczyzno moja!}}\"",
        description: "Say something in Polish:",
    },
    // pages/osx/say.md:28
    MediaExample {
        action: "create_audio_file",
        object_type: "spoken_text",
        scope: "unknown",
        output_form: "audio_file",
        modifiers: &["save_spoken_text"],
        unknown_slots: &["scope"],
        command: "say --output-file {{filename.aiff}} \"{{Here's to the Crazy Ones.}}\"",
        description: "Create an audio file of the spoken text:",
    },
    // pages/osx/screencapture.md:8
    MediaExample {
        action: "capture_still",
        object_type: "screen",
        scope: "screen",
        output_form: "image_file",
        modifiers: &[],
        unknown_slots: &[],
        command: "screencapture {{path/to/file.png}}",
        description: "Take a screenshot and save it to a file:",
    },
    // pages/osx/screencapture.md:12
    MediaExample {
        action: "capture_still",
        object_type: "screen",
        scope: "screen",
        output_form: "image_file",
        modifiers: &["include_cursor"],
        unknown_slots: &[],
        command: "screencapture -C {{path/to/file.png}}",
        description: "Take a screenshot including the mouse cursor:",
    },
    // pages/osx/screencapture.md:16
    MediaExample {
        action: "capture_still",
        object_type: "screen",
        scope: "screen",
        output_form: "preview_app",
        modifiers: &["open_in_preview"],
        unknown_slots: &[],
        command: "screencapture -P",
        description: "Take a screenshot and open it in Preview, instead of saving:",
    },
    // pages/osx/screencapture.md:20
    MediaExample {
        action: "capture_still",
        object_type: "screen_region",
        scope: "selected_rectangular_area",
        output_form: "image_file",
        modifiers: &["interactive_selection"],
        unknown_slots: &[],
        command: "screencapture -i {{path/to/file.png}}",
        description: "Take a screenshot of a selected rectangular area:",
    },
    // pages/osx/screencapture.md:24
    MediaExample {
        action: "capture_still",
        object_type: "screen",
        scope: "screen",
        output_form: "image_file",
        modifiers: &["delay_seconds"],
        unknown_slots: &[],
        command: "screencapture -T {{seconds}} {{path/to/file.png}}",
        description: "Take a screenshot after a delay:",
    },
    // pages/osx/screencapture.md:28
    MediaExample {
        action: "capture_video",
        object_type: "screen",
        scope: "screen",
        output_form: "video_file",
        modifiers: &["record_video"],
        unknown_slots: &[],
        command: "screencapture -v {{path/to/file.mp4}}",
        description: "Make a screen recording and save it to a file:",
    },
];

fn media_variant_entails(request: &MediaRequest, example: &MediaExample) -> bool {
    if example.action != request.action {
        return false;
    }
    if let Some(object_type) = request.object_type {
        if example.object_type != object_type || example.unknown_slots.contains(&"object_type") {
            return false;
        }
    }
    if let Some(scope) = request.scope {
        if example.scope != scope || example.unknown_slots.contains(&"scope") {
            return false;
        }
    }
    if let Some(output_form) = request.output_form {
        if example.output_form != output_form || example.unknown_slots.contains(&"output_form") {
            return false;
        }
    }
    if request
        .modifiers
        .iter()
        .any(|required| !example.modifiers.contains(required))
    {
        return false;
    }
    if let Some(format) = request.output_format {
        let command = example.command.to_ascii_lowercase();
        let description = example.description.to_ascii_lowercase();
        let extension = format!(".{format}");
        if !command.contains(&extension) && !description.contains(format) {
            return false;
        }
    }
    true
}

/// Preserve ordinary search when the query falls outside the narrow media vocabulary.
/// The pinned inventory only proves macOS capabilities.
pub fn allows_answer(query: &str, target_os: crate::search::TargetOs) -> bool {
    if target_os != crate::search::TargetOs::Osx {
        return true;
    }
    parse_media_request(query).is_none_or(|request| {
        MEDIA_EXAMPLES
            .iter()
            .any(|example| media_variant_entails(&request, example))
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::search::TargetOs;

    #[test]
    fn supported_media_examples_remain_available() {
        for query in [
            "Say a phrase aloud",
            "Read a file aloud",
            "Say a phrase with a custom voice and speech rate",
            "Create an AIFF audio file of spoken text",
            "Take a screenshot including the cursor",
            "Take a screenshot and open it in Preview",
            "Capture an interactive rectangular area as a screenshot",
            "Take a screenshot but wait five seconds",
            "Make a screen recording",
        ] {
            assert!(allows_answer(query, TargetOs::Osx), "{query}");
        }
    }

    #[test]
    fn unsupported_clauses_cannot_combine_examples() {
        for query in [
            "Capture an interactive rectangular area as a screenshot but wait five seconds",
            "Read aloud a file while saving the spoken audio simultaneously",
            "Synthesize spoken text as MP3",
            "Record the screen with microphone audio",
            "Take a screenshot and put it on the clipboard",
        ] {
            assert!(!allows_answer(query, TargetOs::Osx), "{query}");
        }
    }

    #[test]
    fn unfamiliar_or_ambiguous_requests_preserve_search() {
        for query in ["Copy a file", "Speak", "Record speech and take screenshots"] {
            assert!(allows_answer(query, TargetOs::Osx), "{query}");
        }
    }

    #[test]
    fn macos_inventory_does_not_gate_other_platforms() {
        let query = "Record the screen with microphone audio";
        assert!(allows_answer(query, TargetOs::Linux));
        assert!(allows_answer(query, TargetOs::Windows));
    }
}

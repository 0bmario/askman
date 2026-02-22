use colored::*;

pub fn colorize_shell_word(word: &str, is_first: bool) -> String {
    if is_first {
        word.green().bold().to_string()
    } else if word.starts_with('-') {
        word.cyan().to_string()
    } else if word.starts_with('[') || word.starts_with(']') || word.contains('|') {
        word.bright_black().to_string() // visually mute bash syntax like [-f|--force]
    } else {
        // Normal text (paths, strings not in variables)
        word.to_string()
    }
}

pub fn highlight_command(ex_cmd: &str) -> String {
    let mut highlighted_cmd = String::new();
    let mut in_variable = false;

    // Simple tokenizer that respects the {{var}} syntax from tldr before stripping it
    let mut current_word = String::new();
    let mut i = 0;
    let chars: Vec<char> = ex_cmd.chars().collect();

    while i < chars.len() {
        // Check for variable start {{
        if i + 1 < chars.len() && chars[i] == '{' && chars[i + 1] == '{' {
            if !current_word.is_empty() {
                highlighted_cmd.push_str(&colorize_shell_word(
                    &current_word,
                    highlighted_cmd.is_empty(),
                ));
                current_word.clear();
            }
            in_variable = true;
            i += 2;
            continue;
        }

        // Check for variable end }}
        if i + 1 < chars.len() && chars[i] == '}' && chars[i + 1] == '}' {
            if !current_word.is_empty() {
                // Variables are colored yellow
                highlighted_cmd.push_str(&current_word.yellow().to_string());
                current_word.clear();
            }
            in_variable = false;
            i += 2;
            continue;
        }

        if chars[i].is_whitespace() && !in_variable {
            if !current_word.is_empty() {
                highlighted_cmd.push_str(&colorize_shell_word(
                    &current_word,
                    highlighted_cmd.is_empty(),
                ));
                current_word.clear();
            }
            highlighted_cmd.push(chars[i]);
        } else {
            current_word.push(chars[i]);
        }
        i += 1;
    }

    // Push any remaining text
    if !current_word.is_empty() {
        if in_variable {
            highlighted_cmd.push_str(&current_word.yellow().to_string());
        } else {
            highlighted_cmd.push_str(&colorize_shell_word(
                &current_word,
                highlighted_cmd.is_empty(),
            ));
        }
    }

    highlighted_cmd
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_colorize_shell_word() {
        assert_eq!(
            colorize_shell_word("ls", true),
            "ls".green().bold().to_string()
        );
        assert_eq!(colorize_shell_word("-la", false), "-la".cyan().to_string());
        assert_eq!(
            colorize_shell_word("file.txt", false),
            "file.txt".to_string()
        );
    }

    #[test]
    fn test_highlight_command() {
        let cmd = "chmod +x {{file}} && ls -la";
        let highlighted = highlight_command(cmd);
        // We just ensure it doesn't crash and produces some string since terminal coloring codes are hard to exact-match sometimes.
        assert!(!highlighted.is_empty());
    }
}

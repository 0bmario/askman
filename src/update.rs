use anyhow::Result;

const UPDATE_COMMAND: &str =
    "curl -fsSL https://raw.githubusercontent.com/0bmario/askman/main/install.sh | bash";

pub fn run_update() -> Result<()> {
    let command = build_update_command();

    println!("askman update is installer-driven.");
    println!("Run this command:");
    println!();
    println!("{command}");

    Ok(())
}

fn build_update_command() -> &'static str {
    // Default behavior: latest update path with minimal friction.
    UPDATE_COMMAND
}

#[cfg(test)]
mod tests {
    use super::build_update_command;

    #[test]
    fn build_latest_update_command() {
        let cmd = build_update_command();
        assert_eq!(
            cmd,
            "curl -fsSL https://raw.githubusercontent.com/0bmario/askman/main/install.sh | bash"
        );
    }
}

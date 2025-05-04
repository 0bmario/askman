use clap::Parser;
use serde::Deserialize;
use std::process;

#[derive(Parser)]
#[command(author, version, about = "askman: Ask terminal commands natively", long_about = None)]
struct Args {
    /// Question as arguments, we need to collect it
    #[arg(required = true)]
    question: Vec<String>,
}

#[derive(Deserialize)]
struct Example {
    keywords: Vec<String>,
    answer: String,
}

fn main() {
    let args = Args::parse();
    let question = args.question.join(" ").to_lowercase();
    println!("Question: {}", question);

    let data = include_str!("../mvp-examples.json");
    let examples: Vec<Example> = serde_json::from_str(data).unwrap_or_else(|err| {
        eprintln!("Error parsing JSON: {}", err);
        process::exit(1);
    });

    // Simple matching: count keyword occurrences
    let mut best: Option<&Example> = None;
    let mut best_score = 0;

    for example in &examples {
        let score = example
            .keywords
            .iter()
            .filter(|kw| question.contains(&kw.to_lowercase()))
            .count();
        if score > best_score {
            best_score = score;
            best = Some(example);
        }
    }

    if let Some(ex) = best {
        println!("\n{}\n", ex.answer);
    } else {
        println!("Sorry, I don't have an example for that yet.");
    }
}

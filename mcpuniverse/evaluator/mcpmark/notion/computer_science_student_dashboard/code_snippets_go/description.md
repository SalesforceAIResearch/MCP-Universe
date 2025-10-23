Find the page named "Computer Science Student Dashboard" and add a new Go column to the "Code Snippets" section.

**Task Requirements:**
1. In the "Code Snippets" section, create (or locate) a column dedicated to the Go programming language. **This column must appear between the existing Python and JavaScript columns** within the same column list.
2. At the top of the Go column, add a bold paragraph that contains exactly the text `Go`.
3. Under the header paragraph, add three code-block blocks configured with `language` set to **go**:
   a. **Basic Go program** – Caption must be `Basic Go program` and the code content must be exactly:
   ```go
   package main

   import "fmt"

   func main() {
       fmt.Println("Hello, World!")
   }
   ```
   b. **For loop in Go** – Caption must be `For loop in Go` and the code content must be exactly:
   ```go
   for i := 0; i < 5; i++ {
       fmt.Println(i)
   }
   ```
   c. **Function definition in Go** – Caption must be `Function definition in Go` and the code content must be exactly:
   ```go
   func add(a, b int) int {
       return a + b
   }
   ```
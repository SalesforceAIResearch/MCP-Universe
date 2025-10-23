Please use FileSystem tools to finish the following task:

**Overview**

The folder "legal_files/" contains all versions (Preferred_Stock_Purchase_Agreement_v0.txt  -- Preferred_Stock_Purchase_Agreement_v10.txt) of the Stock Purchase Agreement for a corporate investment project.

There are comments in it, come from four people:

- **Bill Harvey** (Company CEO)
- **Michelle Jackson** (Investor)
- **David Russel** (Company Counsel)
- **Tony Taylor** (Investor Counsel)

Between v1 and v9, these four people make comments on the clauses. The comment format is `[name:content]`, where:

- `name` is the commenter's name
- `content` is the revision note

**Special Note:** If the name is "All parties", it represents a joint comment from all parties, which counts as one comment but does not count toward any individual's personal comment count.

## Task

Your task is to count the number of comments made by Bill Harvey (Company CEO), Michelle Jackson (Investor), David Russel (Company Counsel), and Tony Taylor (Investor Counsel) in clauses 1.1, 1.3, 4.6, 4.16, 6.8, and 6.16 **in version 5-8.** Please generate `individual_comment.csv` in the **main directory** where the first row contains these clauses (1.1, 1.3, 4.6, 4.16, 6.8, 6.16) and the first column contains the four names (Bill Harvey, Michelle Jackson, David Russel, Tony Taylor). Fill in the table with the number of comments for each person and each clause. If there are no comments, write 0.

using System;
using System.Collections.Generic;

namespace AudionOfficeOcrAi.Core;

/// <summary>
/// The blocks of a long list in two columns. They used to go by turns - the first to the left, the
/// second to the right - and a list whose blocks differ in length left one column half empty: on
/// the page of Craft five cards stood at the left and nine at the right (the owner, 12.10.2026:
/// "the columns must be balanced"). A block now goes to the column that is shorter so far, to the
/// left one when they are level. Blocks of one length still go by turns, and inside a column the
/// blocks keep the order of the list.
/// </summary>
public static class Columns
{
    /// <summary>How tall a block is, counted in cards: the rows of its cards and one more for its heading and rims.</summary>
    public static int Height(int cards, int inARow)
    {
        int row = Math.Max(inARow, 1);
        return 1 + (Math.Max(cards, 0) + row - 1) / row;
    }

    /// <summary>For every block, in the order of the list: false - it goes to the left column, true - to the right one.</summary>
    public static bool[] Right(IReadOnlyList<int> heights)
    {
        var right = new bool[heights.Count];
        int left = 0, other = 0;
        for (int i = 0; i < heights.Count; i++)
        {
            right[i] = other < left;
            if (right[i]) other += heights[i];
            else left += heights[i];
        }
        return right;
    }
}
